from decimal import Decimal
from typing import Any, Optional
import uuid

from django.db import connection, transaction

from identity.models import SystemRoleAssignment
from offers.enums import DecisionDimension, DecisionProfileLifecycleStatus, OfferVersionStatus
from offers.exceptions import (
    DecisionPermissionDeniedError,
    DecisionPolicyError,
    DecisionValidationError,
    OfferNotFoundError,
)
from offers.models.decision import (
    DecisionCandidate,
    DecisionProfileVersion,
    DecisionRun,
    DecisionSignal,
)
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from offers.services.decision_fingerprint import (
    build_canonical_rfq_snapshot,
    compute_decision_run_input_fingerprint,
    compute_decision_run_result_fingerprint,
)
from offers.services.evaluators import (
    evaluate_completeness_signal,
    evaluate_cost_signal,
    evaluate_delivery_signal,
    evaluate_payment_signal,
    evaluate_quality_signal,
    evaluate_trust_signal,
    find_best_same_currency_cost,
)
from offers.services.normalization import normalize_offer_version
from offers.services.policy_seed import (
    DEFAULT_DECISION_PROFILE_CODE,
    seed_decision_profile_v1,
)
from offers.services.scoring import (
    CandidateRankingItem,
    aggregate_candidate_scores,
    evaluate_award_eligibility,
    rank_and_recommend_candidates,
)
from organizations.models import OrganizationMembership
from trade_hub.models import RFQ


def is_operator_or_admin(user: Any) -> bool:
    """Verify if user holds OPERATOR or ADMIN system authority."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


def authorize_decision_actor(rfq: RFQ, actor: Any) -> None:
    """
    Authorize actor to execute or view decision intelligence for an RFQ.

    Permitted:
    - Platform Operators and Product Admins
    - Active members of the RFQ's owning Buyer organization

    Rejected:
    - Unauthenticated callers
    - Foreign Buyer organizations
    - Suppliers and Brokers (even if they have submitted offers on this RFQ)
    - Django staff or superusers without SystemRoleAssignment or RFQ Buyer membership
    """
    if not actor or not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
        raise DecisionPermissionDeniedError("Authentication required to access decision intelligence.")

    if is_operator_or_admin(actor):
        return

    is_rfq_buyer = OrganizationMembership.objects.filter(
        user=actor,
        organization_id=rfq.organization_id,
        is_active=True,
        organization__is_active=True,
    ).exists()

    if not is_rfq_buyer:
        raise DecisionPermissionDeniedError(
            "Actor does not have Buyer or Operator authority for this RFQ's decision intelligence."
        )


def _resolve_rfq(rfq_or_id: Any) -> RFQ:
    if isinstance(rfq_or_id, RFQ):
        return rfq_or_id
    if isinstance(rfq_or_id, (str, uuid.UUID)):
        rfq = (
            RFQ.objects.filter(pk=rfq_or_id)
            .select_related("organization", "commodity", "schema_version")
            .first()
        )
        if not rfq:
            raise OfferNotFoundError(f"RFQ '{rfq_or_id}' does not exist.")
        return rfq
    raise DecisionValidationError(f"Invalid RFQ input: '{rfq_or_id}'.")


def create_decision_run_foundation(
    rfq: RFQ | uuid.UUID | str,
    actor: Any,
    *,
    profile_version: Optional[DecisionProfileVersion] = None,
    engine_version: str = "decision-engine-v1",
) -> DecisionRun:
    """
    Focused internal service to create an immutable DecisionRun foundation record (T0808).

    Execution Steps:
    1. Authorize RFQ decision actor (Buyer or Operator only).
    2. Select exact Published profile version (default to v1 if omitted).
    3. Load current submitted versions using T0806 comparison universe.
    4. Materialize exact candidate set with explicit OfferVersion binding.
    5. Canonicalize inputs and compute SHA-256 input fingerprint.
    6. Persist run and candidates atomically under PostgreSQL REPEATABLE READ snapshot isolation.

    Invariants:
    - Zero recommendation scoring, rank, or signal calculation (T0809 scope).
    - award_eligible defaults to None (safe unevaluated representation).
    - old DecisionRun candidate set is immutable and permanently bound to exact OfferVersion.
    """
    rfq_obj = _resolve_rfq(rfq)

    # 1. Authorize actor
    authorize_decision_actor(rfq_obj, actor)

    # 2. Select exact Published profile version
    if profile_version is None:
        profile_version = (
            DecisionProfileVersion.objects.filter(
                profile__code=DEFAULT_DECISION_PROFILE_CODE,
                status=DecisionProfileLifecycleStatus.PUBLISHED,
            )
            .order_by("-version")
            .first()
        )
        if profile_version is None:
            profile_version = seed_decision_profile_v1()

    if profile_version.status != DecisionProfileLifecycleStatus.PUBLISHED:
        raise DecisionPolicyError(
            f"Only Published decision profile versions can be used for decision runs, got '{profile_version.status}'."
        )

    # 3. Load candidate universe using T0806 semantics and atomic persistence
    with transaction.atomic():
        if connection.vendor == "postgresql" and len(connection.savepoint_ids) == 0:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

        # Load offers that have a current submitted version
        offers = (
            Offer.objects.filter(rfq=rfq_obj, current_submitted_version__isnull=False)
            .select_related(
                "current_submitted_version",
                "current_submitted_version__schema_version",
                "offering_organization",
                "external_counterparty",
            )
            .order_by("id")  # Stable deterministic ordering
        )

        candidate_pairs: list[tuple[Offer, OfferVersion]] = []
        for offer in offers:
            version = offer.current_submitted_version
            if not version:
                continue

            # Candidate Offer must belong to target RFQ
            if offer.rfq_id != rfq_obj.id:
                raise DecisionValidationError(
                    f"Candidate Offer {offer.id} belongs to RFQ {offer.rfq_id}, not {rfq_obj.id}."
                )

            # Version must belong to Offer
            if version.offer_id != offer.id:
                raise DecisionValidationError(
                    f"Candidate OfferVersion {version.id} does not belong to Offer {offer.id}."
                )

            # Version must be SUBMITTED
            if version.status != OfferVersionStatus.SUBMITTED:
                continue

            candidate_pairs.append((offer, version))

        # 4. Canonicalize inputs and compute input fingerprint
        rfq_snapshot = build_canonical_rfq_snapshot(rfq_obj)
        input_fingerprint = compute_decision_run_input_fingerprint(
            rfq=rfq_obj,
            candidate_items=candidate_pairs,
            profile_version=profile_version,
            engine_version=engine_version,
        )

        # 5. Persist DecisionRun
        run = DecisionRun.objects.create(
            rfq=rfq_obj,
            decision_profile_version=profile_version,
            engine_version=engine_version,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
            input_fingerprint=input_fingerprint,
            target_snapshot=rfq_snapshot,
        )

        # 6. Materialize exact candidate records
        candidates = [
            DecisionCandidate(
                decision_run=run,
                offer=offer,
                offer_version=version,
                award_eligible=None,  # Safe unevaluated representation
                decision_score=None,
                evidence_coverage=None,
                effective_score=None,
                rank=None,
            )
            for offer, version in candidate_pairs
        ]
        if candidates:
            DecisionCandidate.objects.bulk_create(candidates)

        return run


def is_decision_run_stale(run: DecisionRun) -> bool:
    """
    Check if the candidate OfferVersion universe evaluated by this DecisionRun
    differs from the RFQ's current submitted versions (T0809, Contract §80).
    """
    return run.is_stale


def execute_decision_run_pipeline(
    rfq: RFQ | uuid.UUID | str,
    actor: Any,
    *,
    profile_version: Optional[DecisionProfileVersion] = None,
    engine_version: str = "decision-engine-v1",
) -> DecisionRun:
    """
    Authoritative synchronous execution of the explainable procurement decision pipeline (T0809).

    Pipeline:
        exact submitted OfferVersions
        -> normalize exact versions (T0805)
        -> evaluate 6 signals (COST, QUALITY, DELIVERY, PAYMENT, TRUST, COMPLETENESS)
        -> aggregate Decimal scores (A, K, C math)
        -> award eligibility gate (hard failure exclusions)
        -> deterministic ranking (effective DESC, coverage DESC, score DESC, stable offer key ASC)
        -> recommendation selection (minimum coverage threshold & top rank)
        -> persist immutable DecisionRun, DecisionCandidate, DecisionSignal
        -> compute deterministic result fingerprint
        -> COMMIT

    Failure Semantics:
        - Handled missing evidence -> UNKNOWN
        - Handled non-applicable -> NOT_APPLICABLE
        - Unhandled runtime provider / system exception -> fails DecisionRun and rolls back transaction.
          Zero partial / corrupted run persisted.
    """
    rfq_obj = _resolve_rfq(rfq)

    # 1. Authorize actor
    authorize_decision_actor(rfq_obj, actor)

    # 2. Select exact Published profile version
    if profile_version is None:
        profile_version = (
            DecisionProfileVersion.objects.filter(
                profile__code=DEFAULT_DECISION_PROFILE_CODE,
                status=DecisionProfileLifecycleStatus.PUBLISHED,
            )
            .order_by("-version")
            .first()
        )
        if profile_version is None:
            profile_version = seed_decision_profile_v1()

    if profile_version.status != DecisionProfileLifecycleStatus.PUBLISHED:
        raise DecisionPolicyError(
            f"Only Published decision profile versions can be used for decision runs, got '{profile_version.status}'."
        )

    dimension_weights = list(profile_version.dimension_weights.all().order_by("dimension"))
    if not dimension_weights:
        raise DecisionPolicyError("DecisionProfileVersion has no dimension weights configured.")

    schema_attributes = list(rfq_obj.schema_version.attributes.all()) if rfq_obj.schema_version_id else []

    # 3. Load candidate universe using atomic persistence with REPEATABLE READ snapshot
    with transaction.atomic():
        if connection.vendor == "postgresql" and len(connection.savepoint_ids) == 0:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

        offers = (
            Offer.objects.filter(rfq=rfq_obj, current_submitted_version__isnull=False)
            .select_related(
                "current_submitted_version",
                "current_submitted_version__schema_version",
                "offering_organization",
                "offering_organization__verification",
                "external_counterparty",
            )
            .prefetch_related(
                "current_submitted_version__cost_components",
            )
            .order_by("id")  # Stable deterministic ordering
        )

        candidate_pairs: list[tuple[Offer, OfferVersion]] = []
        for offer in offers:
            version = offer.current_submitted_version
            if not version:
                continue

            if offer.rfq_id != rfq_obj.id:
                raise DecisionValidationError(
                    f"Candidate Offer {offer.id} belongs to RFQ {offer.rfq_id}, not {rfq_obj.id}."
                )

            if version.offer_id != offer.id:
                raise DecisionValidationError(
                    f"Candidate OfferVersion {version.id} does not belong to Offer {offer.id}."
                )

            if version.status != OfferVersionStatus.SUBMITTED:
                continue

            candidate_pairs.append((offer, version))

        # 4. Canonicalize inputs and compute input fingerprint
        rfq_snapshot = build_canonical_rfq_snapshot(rfq_obj)
        input_fingerprint = compute_decision_run_input_fingerprint(
            rfq=rfq_obj,
            candidate_items=candidate_pairs,
            profile_version=profile_version,
            engine_version=engine_version,
        )

        # 5. Persist DecisionRun foundation
        run = DecisionRun.objects.create(
            rfq=rfq_obj,
            decision_profile_version=profile_version,
            engine_version=engine_version,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
            input_fingerprint=input_fingerprint,
            target_snapshot=rfq_snapshot,
        )

        # 6. Normalize candidates (T0805)
        normalized_candidates = []
        for offer, version in candidate_pairs:
            norm = normalize_offer_version(
                version,
                cost_components=version.cost_components.all(),
            )
            normalized_candidates.append((offer, version, norm))

        # Find best same-currency landed unit cost
        best_cost = find_best_same_currency_cost(
            rfq_obj,
            [(ver, norm) for _, ver, norm in normalized_candidates],
        )

        # 7. Evaluate signals and compute scores per candidate
        intermediate_candidates = []
        for offer, version, norm in normalized_candidates:
            cost_sig = evaluate_cost_signal(rfq_obj, version, norm, best_cost)
            quality_sig = evaluate_quality_signal(rfq_obj, version, schema_attributes=schema_attributes)
            delivery_sig = evaluate_delivery_signal(rfq_obj, version)
            payment_sig = evaluate_payment_signal(rfq_obj, version)
            trust_sig = evaluate_trust_signal(rfq_obj, version)
            completeness_sig = evaluate_completeness_signal(
                rfq_obj, version, norm, reference_time=run.created_at
            )

            signals_map = {
                DecisionDimension.COST: cost_sig,
                DecisionDimension.QUALITY: quality_sig,
                DecisionDimension.DELIVERY: delivery_sig,
                DecisionDimension.PAYMENT: payment_sig,
                DecisionDimension.TRUST: trust_sig,
                DecisionDimension.COMPLETENESS: completeness_sig,
            }

            scores, contributions = aggregate_candidate_scores(signals_map, dimension_weights)

            award_eligible, ineligibility_reasons = evaluate_award_eligibility(
                version,
                signals_map,
                reference_time=run.created_at,
            )

            intermediate_candidates.append({
                "offer": offer,
                "version": version,
                "signals_map": signals_map,
                "scores": scores,
                "contributions": contributions,
                "award_eligible": award_eligible,
                "ineligibility_reasons": ineligibility_reasons,
            })

        # 8. Deterministic Ranking & Recommendation
        ranking_items = [
            CandidateRankingItem(
                offer_id=item["offer"].id,
                offer_version_id=item["version"].id,
                effective_score=item["scores"].effective_score,
                evidence_coverage=item["scores"].evidence_coverage,
                decision_score=item["scores"].decision_score,
                award_eligible=item["award_eligible"],
            )
            for item in intermediate_candidates
        ]

        ranked_items = rank_and_recommend_candidates(
            ranking_items,
            minimum_coverage=profile_version.minimum_coverage,
        )
        ranked_by_offer_id = {item.offer_id: item for item in ranked_items}

        # 9. Persist DecisionCandidate and DecisionSignal records
        persisted_candidates = []
        signals_by_cand_id: dict[uuid.UUID, list[DecisionSignal]] = {}
        dim_weight_map = {dw.dimension: dw.weight for dw in dimension_weights}

        for item in intermediate_candidates:
            offer = item["offer"]
            version = item["version"]
            scores = item["scores"]
            contributions = item["contributions"]
            signals_map = item["signals_map"]
            ranked_info = ranked_by_offer_id[offer.id]

            cand_model = DecisionCandidate(
                decision_run=run,
                offer=offer,
                offer_version=version,
                decision_score=scores.decision_score,
                evidence_coverage=scores.evidence_coverage,
                effective_score=scores.effective_score,
                award_eligible=item["award_eligible"],
                eligibility_reasons=item["ineligibility_reasons"],
                rank=ranked_info.rank,
                is_recommended=ranked_info.is_recommended,
            )
            cand_model.full_clean()
            cand_model.save()
            persisted_candidates.append(cand_model)

            cand_signals: list[DecisionSignal] = []
            for dim in DecisionDimension.values:
                sig_res = signals_map[dim]
                weight_val = dim_weight_map.get(dim)
                sig_model = DecisionSignal(
                    candidate=cand_model,
                    dimension=dim,
                    code=sig_res.code,
                    status=sig_res.status,
                    weight=Decimal(str(weight_val)) if weight_val is not None else None,
                    raw_score=sig_res.raw_score,
                    contribution=contributions.get(dim),
                    expected_value=sig_res.expected_value,
                    actual_value=sig_res.actual_value,
                    reason_code=sig_res.reason_code,
                    snapshot_data=sig_res.snapshot_data,
                )
                sig_model.full_clean()
                sig_model.save()
                cand_signals.append(sig_model)

            signals_by_cand_id[cand_model.id] = cand_signals

        # 10. Result Fingerprint calculation & persistence
        result_fingerprint = compute_decision_run_result_fingerprint(
            run=run,
            candidate_records=persisted_candidates,
            signals_by_candidate_id=signals_by_cand_id,
        )
        run.result_fingerprint = result_fingerprint
        run.save(update_fields=["result_fingerprint"])

        return run


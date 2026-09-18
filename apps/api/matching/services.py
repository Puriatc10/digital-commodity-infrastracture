from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import uuid

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from commodities.models import CommoditySchemaVersion
from geography.models import GeographicArea
from matching.candidates.authorization import validate_actor_audience_authorization
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.service import CandidateDiscoveryService
from matching.candidates.snapshot import CandidateSnapshot
from matching.constants import DEFAULT_ENGINE_VERSION
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalDimension,
    SignalOutcome,
)
from matching.exceptions import (
    NoPublishedPolicyError,
    RFQNotMatchableError,
    RFQNotFoundError,
    UnsupportedAudienceError,
)
from matching.fingerprint import compute_fingerprint
from matching.models.candidate import MatchingCandidate
from matching.models.policy import MatchingPolicyVersion
from matching.models.run import MatchingRun
from matching.models.signal import MatchingSignal
from matching.rules.availability import evaluate_availability
from matching.rules.capability import evaluate_capability
from matching.rules.commodity import evaluate_commodity
from matching.rules.geography import (
    GeographyConstraintSnapshot,
    TargetGeographySnapshot,
    evaluate_geography,
)
from matching.rules.history import (
    HistoricalEvaluationContext,
    evaluate_historical_signals,
)
from matching.rules.lifecycle import evaluate_lifecycle
from matching.rules.quantity import evaluate_quantity
from matching.rules.self_match import evaluate_self_match
from matching.rules.specification import evaluate_candidate_specifications
from matching.rules.trust import evaluate_trust
from matching.seed import (
    DEFAULT_POLICY_CODE,
    seed_matching_policy_v1,
    validate_policy_configuration,
)
from trade_hub.models import RFQ, RFQStatus

logger = logging.getLogger(__name__)


def publish_policy_version(policy_version: MatchingPolicyVersion) -> MatchingPolicyVersion:
    """
    Publish a draft policy version, making its configuration permanently immutable.

    Allowed transitions:
        DRAFT -> PUBLISHED
    """
    if policy_version.status != PolicyLifecycleStatus.DRAFT:
        raise ValidationError(
            f"Cannot publish policy version in '{policy_version.status}' status. Only DRAFT versions can be published."
        )
    policy_version.status = PolicyLifecycleStatus.PUBLISHED
    policy_version.save()
    return policy_version


def retire_policy_version(policy_version: MatchingPolicyVersion) -> MatchingPolicyVersion:
    """
    Retire an existing published policy version.

    Allowed transitions:
        PUBLISHED -> RETIRED
    """
    if policy_version.status != PolicyLifecycleStatus.PUBLISHED:
        raise ValidationError(
            f"Cannot retire policy version in '{policy_version.status}' status. Only PUBLISHED versions can be retired."
        )
    policy_version.status = PolicyLifecycleStatus.RETIRED
    policy_version.save()
    return policy_version


@dataclass(frozen=True)
class EvaluatedSignalData:
    dimension: str
    code: str
    outcome: str
    is_hard: bool
    weight: Decimal
    raw_score: Optional[Decimal]
    contribution: Optional[Decimal]
    reason_code: str
    expected_value: Optional[Dict[str, Any]]
    actual_value: Optional[Dict[str, Any]]
    semantic_identity: Optional[str] = None


@dataclass
class EvaluatedCandidateData:
    snapshot: CandidateSnapshot
    lane: str
    candidate_kind: str
    source_id: str
    stable_candidate_key: str
    is_eligible: bool
    exclusion_code: str
    fit_score: Optional[Decimal]
    evidence_coverage: Optional[Decimal]
    ranking_score: Optional[Decimal]
    rank: Optional[int]
    signals: List[EvaluatedSignalData]


class CachedAncestorLookup:
    """
    In-memory ancestor lookup cache prefetching all GeographicAreas in 1 query.
    Eliminates N+1 queries during geography hierarchy evaluation across candidates.
    """

    def __init__(self):
        self._cache: Dict[str, Tuple[Set[Any], Set[str]]] = {}
        for a in GeographicArea.objects.select_related("parent__parent").all():
            ancestor_ids: Set[Any] = set()
            ancestor_codes: Set[str] = set()
            curr = a.parent
            while curr is not None:
                if curr.id:
                    ancestor_ids.add(curr.id)
                    ancestor_ids.add(str(curr.id))
                if curr.code:
                    ancestor_codes.add(curr.code)
                curr = curr.parent
            self._cache[str(a.id)] = (ancestor_ids, ancestor_codes)
            if a.code:
                self._cache[a.code] = (ancestor_ids, ancestor_codes)

    def __call__(self, area_ref: Any) -> Tuple[Set[Any], Set[str]]:
        if area_ref is None:
            return set(), set()
        area_id = getattr(area_ref, "id", None) or (area_ref if not hasattr(area_ref, "code") else None)
        area_code = getattr(area_ref, "code", "")
        if area_id and str(area_id) in self._cache:
            return self._cache[str(area_id)]
        if area_code and area_code in self._cache:
            return self._cache[area_code]
        return set(), set()


def build_target_snapshot(rfq: RFQ) -> Dict[str, Any]:
    """Materialize an immutable canonical snapshot of RFQ procurement demand."""
    constraints = [
        {
            "mode": c.mode,
            "area_id": str(c.area_id),
            "area_code": c.area.code,
        }
        for c in rfq.geography_constraints.select_related("area").order_by("mode", "area__code")
    ]
    return {
        "rfq_id": str(rfq.id),
        "rfq_version": rfq.version,
        "commodity_id": str(rfq.commodity_id),
        "commodity_code": getattr(rfq.commodity, "code", ""),
        "schema_version_id": str(rfq.schema_version_id),
        "schema_version_number": rfq.schema_version.version,
        "quantity": str(rfq.quantity),
        "unit": rfq.unit,
        "delivery_window_start": (
            rfq.delivery_window_start.isoformat() if rfq.delivery_window_start else None
        ),
        "delivery_window_end": (
            rfq.delivery_window_end.isoformat() if rfq.delivery_window_end else None
        ),
        "destination_area_id": str(rfq.destination_area_id) if rfq.destination_area_id else None,
        "destination_area_code": rfq.destination_area.code if rfq.destination_area else "",
        "geography_constraints": constraints,
        "specifications": dict(sorted(rfq.specifications.items())) if rfq.specifications else {},
    }


class MatchingRunService:
    """
    Focused application orchestrator coordinating candidate discovery, eligibility gates,
    dimension evaluation, 3-part Decimal scoring, lane-local ranking, fingerprints,
    and atomic persistence.
    """

    @classmethod
    def execute_matching_run(
        cls,
        *,
        rfq_id: uuid.UUID | str,
        audience: str,
        actor_scope: ActorScope,
        policy_version_id: Optional[uuid.UUID | str] = None,
        engine_version: str = DEFAULT_ENGINE_VERSION,
        failure_injection_hook: Optional[Callable[[], None]] = None,
    ) -> MatchingRun:
        """
        Execute full matching pipeline against an RFQ inside a PostgreSQL REPEATABLE READ transaction.
        """
        # Validate audience choice
        if audience not in MatchingAudience.values:
            raise UnsupportedAudienceError(
                f"Invalid audience '{audience}'. Must be one of: {', '.join(MatchingAudience.values)}."
            )

        # 1. Resolve and validate policy
        if policy_version_id:
            policy_version = (
                MatchingPolicyVersion.objects.select_related("policy")
                .prefetch_related("verification_rules", "specification_rules")
                .filter(pk=policy_version_id)
                .first()
            )
            if not policy_version or policy_version.status != PolicyLifecycleStatus.PUBLISHED:
                raise NoPublishedPolicyError(
                    f"Policy version '{policy_version_id}' is not an active Published matching policy."
                )
        else:
            policy_version = (
                MatchingPolicyVersion.objects.select_related("policy")
                .prefetch_related("verification_rules", "specification_rules")
                .filter(policy__code=DEFAULT_POLICY_CODE, version=1, status=PolicyLifecycleStatus.PUBLISHED)
                .first()
            )
            if not policy_version:
                policy_version = seed_matching_policy_v1()

        validate_policy_configuration(policy_version.configuration)

        # 2. Begin atomic PostgreSQL REPEATABLE READ transaction
        with transaction.atomic():
            if connection.vendor == "postgresql" and len(connection.savepoint_ids) == 0:
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

            # 3. Retrieve and validate target RFQ
            rfq = (
                RFQ.objects.select_related(
                    "commodity", "schema_version", "organization", "destination_area", "origin_area"
                )
                .prefetch_related("geography_constraints__area")
                .filter(pk=rfq_id)
                .first()
            )
            if not rfq:
                raise RFQNotFoundError(f"RFQ '{rfq_id}' not found.")

            if rfq.status != RFQStatus.PUBLISHED:
                raise RFQNotMatchableError(
                    f"RFQ must be in Published status to execute matching (current status: '{rfq.status}')."
                )

            # 4. Target context & Actor authorization
            context = CandidateContext(
                rfq_id=rfq.id,
                rfq_owner_organization_id=rfq.organization_id,
                commodity_id=rfq.commodity_id,
                audience=audience,
                target_rfq=rfq,
            )
            validate_actor_audience_authorization(actor_scope, context)

            # 5. Build immutable target snapshot
            target_snapshot = build_target_snapshot(rfq)

            # 6. Candidate discovery (Audience-scoped providers)
            discovered_candidates = CandidateDiscoveryService.discover_candidates(context, actor_scope)

            # 7. Pre-cache geography hierarchy and schema versions
            ancestor_lookup = CachedAncestorLookup()
            target_geo_snapshot = TargetGeographySnapshot(
                constraints=tuple(
                    GeographyConstraintSnapshot(
                        mode=c.mode,
                        area=c.area,
                        area_code=c.area.code,
                    )
                    for c in rfq.geography_constraints.all().order_by("mode", "area__code")
                ),
                destination_area=rfq.destination_area,
                destination_area_code=rfq.destination_area.code if rfq.destination_area else "",
            )

            # Extract policy lane weights
            policy_weights = (
                policy_version.configuration.get("dimension_weights")
                or policy_version.configuration.get("weights", {})
            )

            evaluated_candidates: List[EvaluatedCandidateData] = []

            for cand_snap in discovered_candidates:
                eval_data = cls._evaluate_candidate(
                    rfq=rfq,
                    candidate_snapshot=cand_snap,
                    policy_version=policy_version,
                    policy_weights=policy_weights,
                    target_geo_snapshot=target_geo_snapshot,
                    ancestor_lookup=ancestor_lookup,
                    context=context,
                )
                evaluated_candidates.append(eval_data)

            # 8. Lane-local ranking with explicit null handling
            cls._rank_candidates_by_lane(evaluated_candidates)

            # 9. Compute canonical input and result fingerprints
            input_fingerprint = compute_fingerprint({
                "target_snapshot": target_snapshot,
                "candidate_snapshots": [c.snapshot.to_dict() for c in evaluated_candidates],
                "policy_version": policy_version.version,
                "engine_version": engine_version,
                "audience": audience,
            })

            result_fingerprint = compute_fingerprint({
                "candidates": [
                    {
                        "lane": c.lane,
                        "candidate_kind": c.candidate_kind,
                        "source_id": c.source_id,
                        "stable_candidate_key": c.stable_candidate_key,
                        "eligible": c.is_eligible,
                        "exclusion_code": c.exclusion_code,
                        "fit_score": str(c.fit_score) if c.fit_score is not None else None,
                        "evidence_coverage": str(c.evidence_coverage) if c.evidence_coverage is not None else None,
                        "ranking_score": str(c.ranking_score) if c.ranking_score is not None else None,
                        "rank": c.rank,
                        "signals": [
                            {
                                "dimension": s.dimension,
                                "code": s.code,
                                "outcome": s.outcome,
                                "is_hard": s.is_hard,
                                "weight": str(s.weight) if s.weight is not None else None,
                                "raw_score": str(s.raw_score) if s.raw_score is not None else None,
                                "contribution": str(s.contribution) if s.contribution is not None else None,
                                "reason_code": s.reason_code,
                                "expected_value": s.expected_value,
                                "actual_value": s.actual_value,
                                "semantic_identity": s.semantic_identity,
                            }
                            for s in sorted(c.signals, key=lambda s: (s.dimension, s.code))
                        ],
                    }
                    for c in evaluated_candidates
                ]
            })

            # Optional hook for failure injection regression testing
            if failure_injection_hook:
                failure_injection_hook()

            # 10. Persist MatchingRun, Candidates, and Signals atomically
            run = MatchingRun(
                rfq=rfq,
                rfq_version=rfq.version,
                audience=audience,
                requesting_organization=actor_scope.organization if audience == MatchingAudience.BUYER else None,
                requested_by=actor_scope.user if actor_scope.user and actor_scope.user.is_authenticated else None,
                policy_version=policy_version,
                engine_version=engine_version,
                target_snapshot=target_snapshot,
                input_fingerprint=input_fingerprint,
                result_fingerprint=result_fingerprint,
            )
            run.full_clean()
            run.save()

            for c in evaluated_candidates:
                cand_kwargs = {
                    "run": run,
                    "lane": c.lane,
                    "candidate_kind": c.candidate_kind,
                    "candidate_snapshot": c.snapshot.evidence,
                    "eligible": c.is_eligible,
                    "exclusion_code": c.exclusion_code,
                    "fit_score": c.fit_score,
                    "evidence_coverage": c.evidence_coverage,
                    "ranking_score": c.ranking_score,
                    "rank": c.rank,
                    "supplier_organization_id": c.source_id if c.candidate_kind == CandidateKind.SUPPLIER_ORGANIZATION else None,
                    "supply_listing_id": c.source_id if c.candidate_kind == CandidateKind.SUPPLY_LISTING else None,
                    "supply_opportunity_id": c.source_id if c.candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY else None,
                    "broker_organization_id": c.source_id if c.candidate_kind == CandidateKind.BROKER_ORGANIZATION else None,
                }
                cand_model = MatchingCandidate(**cand_kwargs)
                cand_model.full_clean()
                cand_model.save()

                for s in c.signals:
                    sig_model = MatchingSignal(
                        candidate=cand_model,
                        dimension=s.dimension,
                        code=s.code,
                        outcome=s.outcome,
                        is_hard=s.is_hard,
                        weight=s.weight,
                        raw_score=s.raw_score,
                        contribution=s.contribution,
                        expected_value=s.expected_value or {},
                        actual_value=s.actual_value or {},
                        reason_code=s.reason_code,
                        semantic_identity=s.semantic_identity,
                    )
                    sig_model.full_clean()
                    sig_model.save()

            # Safe observability logging
            logger.info(
                "Completed matching run id=%s for rfq=%s version=%s audience=%s policy=%s candidates=%d",
                run.id,
                rfq.id,
                rfq.version,
                audience,
                policy_version.version,
                len(evaluated_candidates),
            )

            return run

    @classmethod
    def _evaluate_candidate(
        cls,
        *,
        rfq: RFQ,
        candidate_snapshot: CandidateSnapshot,
        policy_version: MatchingPolicyVersion,
        policy_weights: Dict[str, Any],
        target_geo_snapshot: TargetGeographySnapshot,
        ancestor_lookup: Callable[[Any], Tuple[Set[Any], Set[str]]],
        context: CandidateContext,
    ) -> EvaluatedCandidateData:
        evidence = candidate_snapshot.evidence
        is_eligible = True
        exclusion_code = ""

        # 1. Core eligibility gates
        # A. Commodity
        comm_res = evaluate_commodity(
            requested_commodity_id=context.commodity_id,
            candidate_commodity_id=evidence.get("commodity_id"),
            candidate_supported_commodity_ids=evidence.get("supported_commodity_ids"),
        )
        if not comm_res.is_eligible:
            is_eligible = False
            if not exclusion_code:
                exclusion_code = comm_res.reason_code

        # B. Capability
        if candidate_snapshot.lane == CandidateLane.POTENTIAL_SUPPLIER:
            cap_res = evaluate_capability("supplier", evidence.get("capabilities", []))
            if not cap_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = cap_res.reason_code
        elif candidate_snapshot.lane == CandidateLane.BROKER_PATH:
            cap_res = evaluate_capability("broker", evidence.get("capabilities", []))
            if not cap_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = cap_res.reason_code

        # C. Self-match
        self_res = evaluate_self_match(
            rfq_owner_organization_id=context.rfq_owner_organization_id,
            candidate_organization_id=evidence.get("organization_id"),
        )
        if not self_res.is_eligible:
            is_eligible = False
            if not exclusion_code:
                exclusion_code = self_res.reason_code

        # D. Source Lifecycle
        cand_status = evidence.get("status", "active")
        if candidate_snapshot.candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY:
            cand_status = evidence.get("status", "Qualified")
        life_res = evaluate_lifecycle(
            candidate_kind=candidate_snapshot.candidate_kind,
            status=cand_status,
            direction=evidence.get("direction", "Supply"),
            is_active=evidence.get("is_active", True),
        )
        if not life_res.is_eligible:
            is_eligible = False
            if not exclusion_code:
                exclusion_code = life_res.reason_code

        # 2. Dimension signals evaluation
        lane_weights = policy_weights.get(candidate_snapshot.lane, {})
        signals: List[EvaluatedSignalData] = []

        if candidate_snapshot.lane == CandidateLane.DIRECT_SUPPLY:
            # Dimension: SPECIFICATION (weight 45)
            cand_schema_ver_id = evidence.get("schema_version_id")
            cand_schema_version = None
            if cand_schema_ver_id:
                cand_schema_version = CommoditySchemaVersion.objects.filter(pk=cand_schema_ver_id).first()

            spec_results = evaluate_candidate_specifications(
                rfq_specifications=rfq.specifications or {},
                rfq_schema_version=rfq.schema_version,
                candidate_specifications=evidence.get("specifications", {}) or {},
                candidate_schema_version=cand_schema_version,
                policy_version=policy_version,
            )

            # Specification dimension base weight
            base_spec_weight = Decimal(str(lane_weights.get(SignalDimension.SPECIFICATION.value, 45)))

            # Calculate applicable rules relative weight sum
            applicable_specs = [
                sr for sr in spec_results
                if sr.outcome != SignalOutcome.NOT_APPLICABLE
            ]
            rel_sum = sum((sr.relative_weight for sr in applicable_specs), Decimal("0"))

            for sr in spec_results:
                if not sr.is_eligible:
                    is_eligible = False
                    if not exclusion_code:
                        exclusion_code = sr.reason_code

                if sr in applicable_specs and rel_sum > Decimal("0"):
                    w = (base_spec_weight * sr.relative_weight / rel_sum).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                else:
                    w = Decimal("0.00")

                raw_s = sr.raw_score
                contrib = (w * raw_s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if raw_s is not None else None

                signals.append(
                    EvaluatedSignalData(
                        dimension=SignalDimension.SPECIFICATION.value,
                        code=sr.code,
                        outcome=sr.outcome,
                        is_hard=sr.is_hard,
                        weight=w,
                        raw_score=raw_s,
                        contribution=contrib,
                        reason_code=sr.reason_code,
                        expected_value=sr.expected,
                        actual_value=sr.actual,
                        semantic_identity=str(sr.semantic_identity_id) if sr.semantic_identity_id else None,
                    )
                )

            # Dimension: QUANTITY (weight 10)
            cand_qty = None
            if evidence.get("quantity") is not None:
                try:
                    cand_qty = Decimal(str(evidence["quantity"]))
                except Exception:
                    cand_qty = None
            cand_unit = evidence.get("unit")
            qty_res = evaluate_quantity(
                requested_quantity=rfq.quantity,
                requested_unit=rfq.unit,
                candidate_quantity=cand_qty,
                candidate_unit=cand_unit,
            )
            if not qty_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = qty_res.reason_code

            qty_weight = Decimal(str(lane_weights.get(SignalDimension.QUANTITY.value, 10)))
            qty_contrib = (
                (qty_weight * qty_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if qty_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.QUANTITY.value,
                    code="quantity",
                    outcome=qty_res.outcome,
                    is_hard=qty_res.is_hard,
                    weight=qty_weight,
                    raw_score=qty_res.raw_score,
                    contribution=qty_contrib,
                    reason_code=qty_res.reason_code,
                    expected_value=qty_res.expected,
                    actual_value=qty_res.actual,
                )
            )

            # Dimension: AVAILABILITY (weight 15)
            cand_start = None
            cand_end = None
            if evidence.get("availability_window_start"):
                try:
                    cand_start = date.fromisoformat(evidence["availability_window_start"])
                except Exception:
                    cand_start = None
            if evidence.get("availability_window_end"):
                try:
                    cand_end = date.fromisoformat(evidence["availability_window_end"])
                except Exception:
                    cand_end = None

            avail_res = evaluate_availability(
                requested_start=rfq.delivery_window_start,
                requested_end=rfq.delivery_window_end,
                candidate_start=cand_start,
                candidate_end=cand_end,
            )
            if not avail_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = avail_res.reason_code

            avail_weight = Decimal(str(lane_weights.get(SignalDimension.AVAILABILITY.value, 15)))
            avail_contrib = (
                (avail_weight * avail_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if avail_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.AVAILABILITY.value,
                    code="availability",
                    outcome=avail_res.outcome,
                    is_hard=avail_res.is_hard,
                    weight=avail_weight,
                    raw_score=avail_res.raw_score,
                    contribution=avail_contrib,
                    reason_code=avail_res.reason_code,
                    expected_value=avail_res.expected,
                    actual_value=avail_res.actual,
                )
            )

            # Dimension: GEOGRAPHY (weight 10)
            cand_geo = candidate_snapshot.to_candidate_geography_snapshot()
            geo_res = evaluate_geography(
                target=target_geo_snapshot,
                candidate=cand_geo,
                ancestor_lookup=ancestor_lookup,
            )
            if not geo_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = geo_res.reason_code

            geo_weight = Decimal(str(lane_weights.get(SignalDimension.GEOGRAPHY.value, 10)))
            geo_contrib = (
                (geo_weight * geo_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if geo_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.GEOGRAPHY.value,
                    code="geography",
                    outcome=geo_res.outcome,
                    is_hard=geo_res.is_hard,
                    weight=geo_weight,
                    raw_score=geo_res.raw_score,
                    contribution=geo_contrib,
                    reason_code=geo_res.reason_code,
                    expected_value=geo_res.expected,
                    actual_value=geo_res.actual,
                )
            )

            # Dimension: TRUST (weight 15)
            trust_res = evaluate_trust(
                candidate=candidate_snapshot,
                policy_version=policy_version,
            )
            if not trust_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = trust_res.reason_code

            trust_weight = Decimal(str(lane_weights.get(SignalDimension.TRUST.value, 15)))
            trust_contrib = (
                (trust_weight * trust_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if trust_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.TRUST.value,
                    code="trust",
                    outcome=trust_res.outcome,
                    is_hard=trust_res.is_hard,
                    weight=trust_weight,
                    raw_score=trust_res.raw_score,
                    contribution=trust_contrib,
                    reason_code=trust_res.reason_code,
                    expected_value=trust_res.expected,
                    actual_value=trust_res.actual,
                )
            )

            # Dimension: HISTORY (weight 5)
            hist_res_list = evaluate_historical_signals(
                candidate=candidate_snapshot,
                context=HistoricalEvaluationContext(
                    audience=context.audience,
                    target_rfq_id=str(rfq.id),
                ),
                policy_version=policy_version,
            )
            base_hist_weight = Decimal(str(lane_weights.get(SignalDimension.HISTORY.value, 5)))
            num_hist = len(hist_res_list) if hist_res_list else 1

            for hr in hist_res_list:
                hr_weight = (base_hist_weight / num_hist).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                hr_contrib = (
                    (hr_weight * hr.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if hr.raw_score is not None
                    else None
                )
                signals.append(
                    EvaluatedSignalData(
                        dimension=SignalDimension.HISTORY.value,
                        code=hr.code,
                        outcome=hr.outcome,
                        is_hard=hr.is_hard,
                        weight=hr_weight,
                        raw_score=hr.raw_score,
                        contribution=hr_contrib,
                        reason_code=hr.reason_code,
                        expected_value=hr.expected,
                        actual_value=hr.actual,
                    )
                )

        elif candidate_snapshot.lane in (CandidateLane.POTENTIAL_SUPPLIER, CandidateLane.BROKER_PATH):
            # Only GEOGRAPHY and TRUST dimensions
            cand_geo = candidate_snapshot.to_candidate_geography_snapshot()
            geo_res = evaluate_geography(
                target=target_geo_snapshot,
                candidate=cand_geo,
                ancestor_lookup=ancestor_lookup,
            )
            if not geo_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = geo_res.reason_code

            geo_weight = Decimal(str(lane_weights.get(SignalDimension.GEOGRAPHY.value, 40)))
            geo_contrib = (
                (geo_weight * geo_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if geo_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.GEOGRAPHY.value,
                    code="geography",
                    outcome=geo_res.outcome,
                    is_hard=geo_res.is_hard,
                    weight=geo_weight,
                    raw_score=geo_res.raw_score,
                    contribution=geo_contrib,
                    reason_code=geo_res.reason_code,
                    expected_value=geo_res.expected,
                    actual_value=geo_res.actual,
                )
            )

            trust_res = evaluate_trust(
                candidate=candidate_snapshot,
                policy_version=policy_version,
            )
            if not trust_res.is_eligible:
                is_eligible = False
                if not exclusion_code:
                    exclusion_code = trust_res.reason_code

            trust_weight = Decimal(str(lane_weights.get(SignalDimension.TRUST.value, 60)))
            trust_contrib = (
                (trust_weight * trust_res.raw_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if trust_res.raw_score is not None
                else None
            )
            signals.append(
                EvaluatedSignalData(
                    dimension=SignalDimension.TRUST.value,
                    code="trust",
                    outcome=trust_res.outcome,
                    is_hard=trust_res.is_hard,
                    weight=trust_weight,
                    raw_score=trust_res.raw_score,
                    contribution=trust_contrib,
                    reason_code=trust_res.reason_code,
                    expected_value=trust_res.expected,
                    actual_value=trust_res.actual,
                )
            )

        # 3. 3-Part Scoring Model
        if is_eligible:
            A = Decimal("0")
            K = Decimal("0")
            C = Decimal("0")
            for sig in signals:
                if sig.outcome != SignalOutcome.NOT_APPLICABLE:
                    A += sig.weight
                    if sig.raw_score is not None:
                        K += sig.weight
                        C += sig.weight * sig.raw_score

            if K > Decimal("0") and A > Decimal("0"):
                fit_score = (Decimal("100") * C / K).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                evidence_coverage = (Decimal("100") * K / A).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ranking_score = (Decimal("100") * C / A).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                fit_score = None
                evidence_coverage = Decimal("0.00")
                ranking_score = Decimal("0.00")
        else:
            fit_score = None
            evidence_coverage = None
            ranking_score = None

        return EvaluatedCandidateData(
            snapshot=candidate_snapshot,
            lane=candidate_snapshot.lane,
            candidate_kind=candidate_snapshot.candidate_kind,
            source_id=candidate_snapshot.source_id,
            stable_candidate_key=candidate_snapshot.stable_candidate_key,
            is_eligible=is_eligible,
            exclusion_code=exclusion_code,
            fit_score=fit_score,
            evidence_coverage=evidence_coverage,
            ranking_score=ranking_score,
            rank=None,
            signals=signals,
        )

    @classmethod
    def _rank_candidates_by_lane(cls, candidates: List[EvaluatedCandidateData]) -> None:
        """
        Rank candidates strictly within their respective lanes.
        Tie-breaker order:
            eligible DESC
            ranking_score DESC (nulls last)
            evidence_coverage DESC (nulls last)
            fit_score DESC (nulls last)
            stable_candidate_key ASC
        Eligible candidates receive rank 1, 2, 3...
        Ineligible candidates receive rank=None.
        """
        candidates_by_lane: Dict[str, List[EvaluatedCandidateData]] = {}
        for c in candidates:
            candidates_by_lane.setdefault(c.lane, []).append(c)

        for lane, lane_cands in candidates_by_lane.items():
            def sort_key(item: EvaluatedCandidateData):
                return (
                    0 if item.is_eligible else 1,
                    (0, -item.ranking_score) if item.ranking_score is not None else (1, Decimal("0")),
                    (0, -item.evidence_coverage) if item.evidence_coverage is not None else (1, Decimal("0")),
                    (0, -item.fit_score) if item.fit_score is not None else (1, Decimal("0")),
                    item.stable_candidate_key,
                )

            lane_cands.sort(key=sort_key)

            current_rank = 1
            for c in lane_cands:
                if c.is_eligible:
                    c.rank = current_rank
                    current_rank += 1
                else:
                    c.rank = None

        # Re-sort full list deterministically: lane ASC, then rank (nulls last), then stable_candidate_key ASC
        candidates.sort(
            key=lambda item: (
                item.lane,
                0 if item.is_eligible else 1,
                item.rank if item.rank is not None else 999999,
                item.stable_candidate_key,
            )
        )


# Convenience module-level entry points
execute_matching_run = MatchingRunService.execute_matching_run


@transaction.atomic
def create_matching_run(
    *,
    rfq: Any,
    rfq_version: int,
    audience: str,
    policy_version: MatchingPolicyVersion,
    requesting_organization: Optional[Any] = None,
    requested_by: Optional[Any] = None,
    target_snapshot: Optional[dict] = None,
    engine_version: str = DEFAULT_ENGINE_VERSION,
    input_fingerprint: str = "",
    result_fingerprint: str = "",
) -> MatchingRun:
    """
    Backward-compatible domain service entry point for persisting a raw MatchingRun instance.
    """
    if policy_version.status != PolicyLifecycleStatus.PUBLISHED:
        raise ValidationError(
            f"Matching runs can only be created against a PUBLISHED policy version (current status: '{policy_version.status}')."
        )

    if audience not in MatchingAudience.values:
        raise ValidationError(f"Invalid audience '{audience}'. Must be one of: {', '.join(MatchingAudience.values)}.")

    snapshot = target_snapshot or {}
    if not input_fingerprint and snapshot:
        input_fingerprint = compute_fingerprint({
            "target_snapshot": snapshot,
            "policy_version": policy_version.version,
            "engine_version": engine_version,
            "audience": audience,
        })

    run = MatchingRun(
        rfq=rfq,
        rfq_version=rfq_version,
        audience=audience,
        requesting_organization=requesting_organization,
        requested_by=requested_by,
        policy_version=policy_version,
        engine_version=engine_version,
        target_snapshot=snapshot,
        input_fingerprint=input_fingerprint,
        result_fingerprint=result_fingerprint,
    )
    run.full_clean()
    run.save()
    return run

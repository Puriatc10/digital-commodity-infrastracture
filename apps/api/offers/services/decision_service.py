from typing import Any, Optional
import uuid

from django.db import connection, transaction

from identity.models import SystemRoleAssignment
from offers.enums import DecisionProfileLifecycleStatus, OfferVersionStatus
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
)
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from offers.services.decision_fingerprint import (
    build_canonical_rfq_snapshot,
    compute_decision_run_input_fingerprint,
)
from offers.services.policy_seed import (
    DEFAULT_DECISION_PROFILE_CODE,
    seed_decision_profile_v1,
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

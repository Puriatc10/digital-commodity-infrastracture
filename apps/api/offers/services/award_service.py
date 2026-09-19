from decimal import Decimal
from typing import Any, Optional

from django.db import models, transaction
from django.utils import timezone

from identity.models import SystemRoleAssignment
from offers.enums import AwardStatus, DecisionSignalStatus, OfferVersionStatus
from offers.exceptions import (
    AwardConflictError,
    AwardEligibilityError,
    AwardImmutableError,
    AwardNotFoundError,
    AwardAllocationNotFoundError,
    AwardPermissionDeniedError,
    AwardValidationError,
    InvalidVersionError,
    OfferNotFoundError,
    OfferStateError,
    OfferVersionNotFoundError,
    StaleVersionError,
)
from offers.models import Award, AwardAllocation, Offer, OfferVersion
from offers.services.evaluators.quality import evaluate_quality_signal
from opportunities.models import OpportunityDirection, OpportunityStatus
from organizations.models import OrganizationMembership
from organizations.verification.models import VerificationStatus
from trade_hub.models import RFQ, RFQStatus
from trade_hub.services.rfq_lifecycle import award_rfq


def _is_operator_or_admin(user: Any) -> bool:
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


def _check_award_authority(rfq: RFQ, actor: Any) -> None:
    """
    Verify if actor is authorized to manage or finalize an Award for the RFQ.

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active OWNER, MANAGER, or MEMBER of the RFQ's owning Buyer organization.

    Denied:
    - Competitor Suppliers / Brokers.
    - Foreign Buyers.
    - Inactive members or viewers.
    - Django staff-only / superuser-only without system role.
    - Unauthenticated users.
    """
    if not actor or not getattr(actor, "is_authenticated", False):
        raise AwardPermissionDeniedError("Authentication required.")

    if _is_operator_or_admin(actor):
        return

    is_buyer_member = OrganizationMembership.objects.filter(
        user=actor,
        organization_id=rfq.organization_id,
        is_active=True,
        organization__is_active=True,
        role__in=[
            OrganizationMembership.OrganizationRole.OWNER,
            OrganizationMembership.OrganizationRole.MANAGER,
            OrganizationMembership.OrganizationRole.MEMBER,
        ],
    ).exists()

    if not is_buyer_member:
        raise AwardPermissionDeniedError(
            "Actor lacks authorization to manage or finalize awards for this RFQ."
        )


def _validate_expected_version(current_version: int, expected_version: Any) -> None:
    """Validate optimistic concurrency expected_version against aggregate version."""
    if expected_version is None:
        raise InvalidVersionError("expected_version is strictly required.")
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if current_version != expected_version:
        raise StaleVersionError(
            f"Stale version error: Award version is {current_version}, expected {expected_version}."
        )


@transaction.atomic
def create_draft_award(rfq_id: Any, *, actor: Any) -> Award:
    """
    Create a new Draft Award aggregate for the target RFQ (Contract §63, T0813).

    Guarantees exactly one Award per RFQ.
    Permitted only when RFQ is in COLLECTING_OFFERS or NEGOTIATING.
    """
    rfq = RFQ.objects.select_for_update().filter(pk=rfq_id).first()
    if not rfq:
        raise OfferNotFoundError(f"RFQ '{rfq_id}' does not exist.")

    _check_award_authority(rfq, actor)

    if rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
        raise OfferStateError(
            f"Cannot create award for RFQ in terminal status '{rfq.status}'."
        )

    if rfq.status not in (RFQStatus.COLLECTING_OFFERS, RFQStatus.NEGOTIATING):
        raise OfferStateError(
            f"Cannot create award for RFQ in status '{rfq.status}'. "
            f"Only RFQs in Collecting Offers or Negotiating can be awarded."
        )

    # Enforce exactly one Award aggregate per RFQ
    existing_award = Award.objects.filter(rfq=rfq).first()
    if existing_award:
        raise AwardConflictError(
            f"An award aggregate already exists for RFQ '{rfq.id}' (id: {existing_award.id})."
        )

    award = Award.objects.create(
        rfq=rfq,
        status=AwardStatus.DRAFT,
        version=1,
        created_by=actor,
    )
    return award


@transaction.atomic
def add_award_allocation(
    award_id: Any,
    *,
    offer_version_id: Any,
    awarded_quantity: Any,
    quantity_unit: Optional[str] = None,
    expected_version: Any,
    actor: Any,
) -> AwardAllocation:
    """
    Add a commercial allocation to a Draft Award (Contract §64, §65, T0813).

    Enforces stable lock order: RFQ -> Award -> Offer -> OfferVersion.
    Requires expected_version for optimistic concurrency control.
    Binds allocation to an exact, submitted, current OfferVersion.
    """
    award_pre = Award.objects.filter(pk=award_id).only("id", "rfq_id").first()
    if not award_pre:
        raise AwardNotFoundError(f"Award '{award_id}' does not exist.")

    # 1. Lock RFQ
    locked_rfq = RFQ.objects.select_for_update().get(pk=award_pre.rfq_id)

    # 2. Lock Award
    locked_award = Award.objects.select_for_update().get(pk=award_id)

    _check_award_authority(locked_rfq, actor)
    _validate_expected_version(locked_award.version, expected_version)

    if locked_award.status != AwardStatus.DRAFT:
        raise AwardImmutableError("Cannot add allocation to a finalized Award.")

    if locked_rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
        raise OfferStateError(
            f"Cannot add allocation for RFQ in terminal status '{locked_rfq.status}'."
        )

    # 3. Lock Offer and OfferVersion
    version = (
        OfferVersion.objects.select_for_update()
        .select_related("offer")
        .filter(pk=offer_version_id)
        .first()
    )
    if not version:
        raise OfferVersionNotFoundError(f"OfferVersion '{offer_version_id}' does not exist.")

    offer = Offer.objects.select_for_update().filter(pk=version.offer_id).first()
    if not offer:
        raise OfferNotFoundError(f"Offer '{version.offer_id}' does not exist.")

    # Validate version belongs to the RFQ
    if offer.rfq_id != locked_rfq.id:
        raise AwardValidationError(
            f"Offer '{offer.id}' does not belong to Award RFQ '{locked_rfq.id}'."
        )

    # Validate version status is SUBMITTED
    if version.status != OfferVersionStatus.SUBMITTED:
        raise AwardValidationError(
            f"Cannot allocate OfferVersion in status '{version.status}'. Only SUBMITTED versions are eligible."
        )

    # Validate version is the current submitted version
    if offer.current_submitted_version_id != version.id:
        raise AwardValidationError(
            f"OfferVersion '{version.id}' is not the current submitted version for Offer '{offer.id}'. "
            f"A newer version exists."
        )

    # Parse and validate quantity
    try:
        qty = Decimal(str(awarded_quantity))
    except Exception as exc:
        raise AwardValidationError(f"Invalid awarded_quantity '{awarded_quantity}': must be a valid Decimal.") from exc

    if qty <= Decimal("0"):
        raise AwardValidationError("Awarded quantity must be strictly greater than zero.")

    if qty > version.offered_quantity:
        raise AwardValidationError(
            f"Awarded quantity ({qty}) exceeds offered quantity ({version.offered_quantity})."
        )

    resolved_unit = quantity_unit or version.quantity_unit
    if resolved_unit != version.quantity_unit or resolved_unit != locked_rfq.unit:
        raise AwardValidationError(
            f"Quantity unit mismatch: requested '{resolved_unit}', offer version is '{version.quantity_unit}', "
            f"RFQ unit is '{locked_rfq.unit}'."
        )

    # Check for duplicate exact snapshot allocation
    if AwardAllocation.objects.filter(award=locked_award, offer_version=version).exists():
        raise AwardConflictError(
            f"An allocation for OfferVersion '{version.id}' already exists in this Award."
        )

    # Check for existing allocation for this Offer thread
    if AwardAllocation.objects.filter(award=locked_award, offer=offer).exists():
        raise AwardConflictError(
            f"An allocation for Offer '{offer.id}' already exists in this Award."
        )

    # Check total quantity across allocations
    current_total = (
        AwardAllocation.objects.filter(award=locked_award).aggregate(
            total=models.Sum("awarded_quantity")
        )["total"]
        or Decimal("0")
    )
    if current_total + qty > locked_rfq.quantity:
        raise AwardValidationError(
            f"Total awarded quantity ({current_total + qty}) exceeds RFQ requested quantity ({locked_rfq.quantity})."
        )

    allocation = AwardAllocation.objects.create(
        award=locked_award,
        offer=offer,
        offer_version=version,
        awarded_quantity=qty,
        quantity_unit=resolved_unit,
    )

    # Advance Award version atomically
    locked_award.version += 1
    locked_award.save(update_fields=["version", "updated_at"])

    return allocation


@transaction.atomic
def update_award_allocation(
    allocation_id: Any,
    *,
    awarded_quantity: Any,
    expected_version: Any,
    actor: Any,
) -> AwardAllocation:
    """
    Update the allocated quantity of an existing AwardAllocation (Contract §65, T0813).

    Enforces stable lock order: RFQ -> Award -> Allocation.
    Requires expected_version for optimistic concurrency control.
    """
    alloc_pre = AwardAllocation.objects.filter(pk=allocation_id).select_related("award").first()
    if not alloc_pre:
        raise AwardAllocationNotFoundError(f"AwardAllocation '{allocation_id}' does not exist.")

    # 1. Lock RFQ
    locked_rfq = RFQ.objects.select_for_update().get(pk=alloc_pre.award.rfq_id)

    # 2. Lock Award
    locked_award = Award.objects.select_for_update().get(pk=alloc_pre.award_id)

    _check_award_authority(locked_rfq, actor)
    _validate_expected_version(locked_award.version, expected_version)

    if locked_award.status != AwardStatus.DRAFT:
        raise AwardImmutableError("Cannot update allocation in a finalized Award.")

    # 3. Lock Allocation and OfferVersion
    locked_alloc = (
        AwardAllocation.objects.select_for_update()
        .select_related("offer_version")
        .get(pk=allocation_id)
    )

    try:
        qty = Decimal(str(awarded_quantity))
    except Exception as exc:
        raise AwardValidationError(f"Invalid awarded_quantity '{awarded_quantity}': must be a valid Decimal.") from exc

    if qty <= Decimal("0"):
        raise AwardValidationError("Awarded quantity must be strictly greater than zero.")

    if qty > locked_alloc.offer_version.offered_quantity:
        raise AwardValidationError(
            f"Awarded quantity ({qty}) exceeds offered quantity ({locked_alloc.offer_version.offered_quantity})."
        )

    # Check total quantity across allocations
    other_total = (
        AwardAllocation.objects.filter(award=locked_award)
        .exclude(pk=locked_alloc.pk)
        .aggregate(total=models.Sum("awarded_quantity"))["total"]
        or Decimal("0")
    )
    if other_total + qty > locked_rfq.quantity:
        raise AwardValidationError(
            f"Total awarded quantity ({other_total + qty}) exceeds RFQ requested quantity ({locked_rfq.quantity})."
        )

    locked_alloc.awarded_quantity = qty
    locked_alloc.save(update_fields=["awarded_quantity", "updated_at"])

    # Advance Award version atomically
    locked_award.version += 1
    locked_award.save(update_fields=["version", "updated_at"])

    return locked_alloc


@transaction.atomic
def remove_award_allocation(
    allocation_id: Any,
    *,
    expected_version: Any,
    actor: Any,
) -> None:
    """
    Remove an allocation from a Draft Award (Contract §64, T0813).

    Enforces stable lock order: RFQ -> Award -> Allocation.
    Requires expected_version for optimistic concurrency control.
    """
    alloc_pre = AwardAllocation.objects.filter(pk=allocation_id).select_related("award").first()
    if not alloc_pre:
        raise AwardAllocationNotFoundError(f"AwardAllocation '{allocation_id}' does not exist.")

    # 1. Lock RFQ
    locked_rfq = RFQ.objects.select_for_update().get(pk=alloc_pre.award.rfq_id)

    # 2. Lock Award
    locked_award = Award.objects.select_for_update().get(pk=alloc_pre.award_id)

    _check_award_authority(locked_rfq, actor)
    _validate_expected_version(locked_award.version, expected_version)

    if locked_award.status != AwardStatus.DRAFT:
        raise AwardImmutableError("Cannot remove allocation from a finalized Award.")

    locked_alloc = AwardAllocation.objects.select_for_update().get(pk=allocation_id)
    locked_alloc.delete()

    # Advance Award version atomically
    locked_award.version += 1
    locked_award.save(update_fields=["version", "updated_at"])


@transaction.atomic
def finalize_award(
    award_id: Any,
    *,
    expected_version: Any,
    actor: Any,
) -> Award:
    """
    Authoritatively finalize an Award aggregate and transition the RFQ to Awarded (Contract §68, T0813).

    Execution Contract:
    1. Lock RFQ exclusive row.
    2. Lock Award exclusive row.
    3. Validate actor authority (Buyer active member or Operator/Admin).
    4. Validate expected_version matches Award version.
    5. Validate Award is in DRAFT status.
    6. Validate RFQ is in COLLECTING_OFFERS or NEGOTIATING (reject terminal states).
    7. Require at least one AwardAllocation.
    8. Lock selected Offers in sorted order.
    9. Lock selected OfferVersions in sorted order.
    10. Snapshot authoritative server timestamp.
    11. Re-check for every allocation:
        - Offer targets Award RFQ
        - OfferVersion belongs to Offer
        - OfferVersion is SUBMITTED
        - OfferVersion == Offer.current_submitted_version (rejects stale revisions)
        - awarded_quantity > 0 and <= offered_quantity
        - unit compatibility
        - Expiry check against server timestamp
        - Internal organization trust: reject if SUSPENDED
        - External offer provenance: validate qualified supply opportunity
        - Hard technical compliance: evaluate_quality_signal
    12. Check total quantity: sum(awarded_quantity) <= RFQ requested quantity.
    13. Transition Award -> FINALIZED with finalized_by, finalized_at, version += 1.
    14. Transition RFQ -> AWARDED using RFQLifecycleService.award_rfq.
    15. Commit transaction. Strictly NO Deal or DealAllocation created.
    """
    award_pre = Award.objects.filter(pk=award_id).only("id", "rfq_id").first()
    if not award_pre:
        raise AwardNotFoundError(f"Award '{award_id}' does not exist.")

    # 1. Lock RFQ
    locked_rfq = (
        RFQ.objects.select_for_update()
        .select_related("commodity", "schema_version", "organization")
        .get(pk=award_pre.rfq_id)
    )

    # 2. Lock Award
    locked_award = Award.objects.select_for_update().get(pk=award_id)

    _check_award_authority(locked_rfq, actor)
    _validate_expected_version(locked_award.version, expected_version)

    if locked_award.status == AwardStatus.FINALIZED:
        raise AwardConflictError(f"Award '{award_id}' is already finalized.")

    if locked_award.status != AwardStatus.DRAFT:
        raise AwardImmutableError(f"Cannot finalize Award in status '{locked_award.status}'.")

    if locked_rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
        raise OfferStateError(
            f"Cannot finalize award for RFQ in terminal status '{locked_rfq.status}'."
        )

    if locked_rfq.status not in (RFQStatus.COLLECTING_OFFERS, RFQStatus.NEGOTIATING):
        raise OfferStateError(
            f"Cannot finalize award for RFQ in status '{locked_rfq.status}'. "
            f"Only RFQs in Collecting Offers or Negotiating can be awarded."
        )

    # 7. Require at least one allocation
    allocations = list(
        AwardAllocation.objects.filter(award=locked_award)
        .select_related("offer", "offer_version")
    )
    if not allocations:
        raise AwardValidationError("Cannot finalize an Award with no allocations.")

    # 8 & 9. Lock selected Offers and OfferVersions in sorted order
    offer_ids = sorted({alloc.offer_id for alloc in allocations})
    version_ids = sorted({alloc.offer_version_id for alloc in allocations})

    locked_offers = {
        o.id: o
        for o in Offer.objects.filter(id__in=offer_ids)
        .select_for_update()
        .order_by("id")
    }

    locked_versions = {
        v.id: v
        for v in OfferVersion.objects.filter(id__in=version_ids)
        .select_for_update()
        .order_by("id")
    }


    # 10. Authoritative server-time snapshot
    now = timezone.now()

    # 11. Re-validate each allocation
    total_awarded = Decimal("0")
    for alloc in allocations:
        offer = locked_offers.get(alloc.offer_id)
        version = locked_versions.get(alloc.offer_version_id)

        if not offer or not version:
            raise AwardEligibilityError("Referenced Offer or OfferVersion could not be locked.")

        # Target RFQ
        if offer.rfq_id != locked_rfq.id:
            raise AwardEligibilityError(
                f"Offer '{offer.id}' does not target Award RFQ '{locked_rfq.id}'."
            )

        # Version belongs to Offer
        if version.offer_id != offer.id:
            raise AwardEligibilityError(
                f"OfferVersion '{version.id}' does not belong to Offer '{offer.id}'."
            )

        # Version is SUBMITTED
        if version.status != OfferVersionStatus.SUBMITTED:
            raise AwardEligibilityError(
                f"OfferVersion '{version.id}' is not in SUBMITTED status (found '{version.status}')."
            )

        # Version is current submitted version of Offer
        if offer.current_submitted_version_id != version.id:
            raise AwardEligibilityError(
                f"OfferVersion '{version.id}' is not the current submitted version for Offer '{offer.id}'. "
                f"A revised version has been submitted."
            )

        # Quantity invariants
        if alloc.awarded_quantity <= Decimal("0"):
            raise AwardValidationError(
                f"Awarded quantity for allocation '{alloc.id}' must be greater than zero."
            )

        if alloc.awarded_quantity > version.offered_quantity:
            raise AwardValidationError(
                f"Awarded quantity ({alloc.awarded_quantity}) exceeds offered quantity ({version.offered_quantity}) "
                f"for Offer '{offer.id}'."
            )

        # Unit compatibility
        if alloc.quantity_unit != locked_rfq.unit or version.quantity_unit != locked_rfq.unit:
            raise AwardValidationError(
                f"Unit mismatch on allocation '{alloc.id}': allocation unit '{alloc.quantity_unit}', "
                f"version unit '{version.quantity_unit}', RFQ unit '{locked_rfq.unit}'."
            )

        # Expiry check
        if version.valid_until and version.valid_until < now:
            raise AwardEligibilityError(
                f"Offer '{offer.id}' V{version.version_number} expired at {version.valid_until} (server time: {now})."
            )

        # Internal organization trust check: reject Suspended
        if offer.offering_organization_id:
            org = offer.offering_organization
            if not org.is_active:
                raise AwardEligibilityError(f"Offering organization '{org.name}' is inactive.")
            verification = getattr(org, "verification", None)
            ver_status = (verification.status if verification else "unverified").lower()
            if ver_status == VerificationStatus.SUSPENDED:
                raise AwardEligibilityError(
                    f"Offering organization '{org.name}' is SUSPENDED and not eligible for award."
                )

        # External counterparty provenance check
        if offer.external_counterparty_id:
            if not offer.source_opportunity_id or not offer.source_opportunity:
                raise AwardEligibilityError(
                    f"External offer '{offer.id}' lacks qualified source opportunity provenance."
                )
            source_opp = offer.source_opportunity
            if source_opp.direction != OpportunityDirection.SUPPLY:
                raise AwardEligibilityError(
                    f"External offer source opportunity '{source_opp.id}' direction must be SUPPLY (found '{source_opp.direction}')."
                )
            if source_opp.status != OpportunityStatus.QUALIFIED:
                raise AwardEligibilityError(
                    f"External offer source opportunity '{source_opp.id}' status must be QUALIFIED (found '{source_opp.status}')."
                )
            if source_opp.external_counterparty_id != offer.external_counterparty_id:
                raise AwardEligibilityError(
                    "External offer source opportunity counterparty mismatch."
                )

        # Hard technical specification eligibility check
        quality_res = evaluate_quality_signal(locked_rfq, version)
        if quality_res.is_hard_failure or quality_res.status == DecisionSignalStatus.FAIL:
            reasons = quality_res.snapshot_data.get("failed_keys", [])
            raise AwardEligibilityError(
                f"Offer '{offer.id}' V{version.version_number} fails hard technical specifications: "
                f"reason={quality_res.reason_code}, failed_keys={reasons}."
            )

        total_awarded += alloc.awarded_quantity

    # 12. Validate total quantity across allocations
    if total_awarded <= Decimal("0"):
        raise AwardValidationError("Total awarded quantity must be greater than zero.")

    if total_awarded > locked_rfq.quantity:
        raise AwardValidationError(
            f"Total awarded quantity ({total_awarded}) exceeds RFQ requested quantity ({locked_rfq.quantity})."
        )

    # 13. Finalize Award
    locked_award.status = AwardStatus.FINALIZED
    locked_award.finalized_by = actor
    locked_award.finalized_at = now
    locked_award.version += 1
    locked_award.save(
        update_fields=["status", "finalized_by", "finalized_at", "version", "updated_at"]
    )

    # 14. Transition RFQ to AWARDED via authoritative lifecycle service
    award_rfq(locked_rfq, actor=actor)

    return locked_award

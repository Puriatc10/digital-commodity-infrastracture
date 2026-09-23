from typing import Any, Optional

from django.db import transaction

from deals.exceptions import (
    AwardNotFinalizedError,
    AwardNotFoundError,
    DealPermissionDeniedError,
    DealSourceIntegrityError,
    DealValidationError,
    StaleVersionError,
)
from deals.models import Deal
from identity.models import SystemRoleAssignment
from offers.enums import AwardStatus
from offers.models import Award, AwardAllocation
from organizations.models import OrganizationMembership
from trade_hub.models import RFQ


def _is_operator_or_admin(user: Any) -> bool:
    """Verify if user holds OPERATOR or ADMIN system role authority."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


def _check_deal_materialize_authority(rfq: RFQ, actor: Any) -> None:
    """
    Verify if actor is authorized to materialize deals for the Award/RFQ.

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active OWNER, MANAGER, or MEMBER of the RFQ's owning Buyer organization.

    Denied:
    - Competitor Suppliers / Brokers.
    - Foreign Buyers.
    - Inactive members or viewers (VIEWER is read-only).
    - Django staff-only / superuser-only without system role.
    - Unauthenticated users.
    """
    if not actor or not getattr(actor, "is_authenticated", False):
        raise DealPermissionDeniedError("Authentication required.")

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
        raise DealPermissionDeniedError(
            "Actor lacks authorization to materialize deals for this Award/RFQ."
        )


@transaction.atomic
def materialize_deals_from_award(
    award_id: Any,
    *,
    actor: Any,
    expected_version: Optional[int] = None,
) -> tuple[list[Deal], bool]:
    """
    Materialize authoritative commercial Deals from a FINALIZED Award (Epic 9 Contract §60, T0901).

    Responsibilities:
    1. Lock RFQ and Award rows with select_for_update.
    2. Authorize actor (Buyer Owner/Manager/Member or Platform Operator/Admin).
    3. Require Award status == FINALIZED (rejects DRAFT with AwardNotFinalizedError).
    4. If expected_version provided, enforce optimistic concurrency check.
    5. Load AwardAllocations deterministically in stable order under row locks.
    6. Validate source graph integrity (allocation -> award -> rfq -> offer -> offer_version).
    7. Return existing Deals for already materialized allocations (idempotent).
    8. Derive Buyer strictly from RFQ owning Organization.
    9. Derive Seller strictly from Offer economic party (Supplier/Broker Organization or ExternalCounterparty).
    10. Create missing Deal identities atomically.
    11. Commit atomically; midway failure rolls back newly materialized deals without touching existing ones.

    Returns:
        tuple[list[Deal], bool]: (all_deals_for_award, newly_created_flag)
    """
    award_pre = Award.objects.filter(pk=award_id).only("id", "rfq_id").first()
    if not award_pre:
        raise AwardNotFoundError(f"Award '{award_id}' does not exist.")

    # 1. Lock RFQ & Award
    locked_rfq = (
        RFQ.objects.select_for_update()
        .select_related("organization")
        .get(pk=award_pre.rfq_id)
    )
    locked_award = Award.objects.select_for_update().get(pk=award_id)

    # 2. Authorize Actor
    _check_deal_materialize_authority(locked_rfq, actor)

    # 3. Require FINALIZED
    if locked_award.status != AwardStatus.FINALIZED:
        raise AwardNotFinalizedError(
            f"Cannot materialize deals for Award in status '{locked_award.status}'. "
            f"Award must be FINALIZED before materialization."
        )

    # 4. Validate expected_version if provided
    if expected_version is not None:
        if type(expected_version) is not int or isinstance(expected_version, bool) or expected_version < 1:
            raise DealValidationError(
                f"expected_version must be a positive integer, got {expected_version}."
            )
        if locked_award.version != expected_version:
            raise StaleVersionError(
                f"Stale version error: Award version is {locked_award.version}, expected {expected_version}."
            )

    # 5. Load AwardAllocations deterministically under row lock
    alloc_ids = list(
        AwardAllocation.objects.select_for_update()
        .filter(award=locked_award)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    if not alloc_ids:
        raise DealValidationError(
            f"Award '{locked_award.id}' has no allocations to materialize."
        )

    allocations = list(
        AwardAllocation.objects.filter(id__in=alloc_ids)
        .select_related(
            "offer",
            "offer__offering_organization",
            "offer__external_counterparty",
            "offer_version",
        )
        .order_by("created_at", "id")
    )

    # 6. Check existing Deals for these allocations
    existing_deals = {
        deal.award_allocation_id: deal
        for deal in Deal.objects.select_for_update().filter(award_allocation__in=allocations)
    }

    newly_created = False

    # 7. Create missing Deals
    for allocation in allocations:
        if allocation.id in existing_deals:
            continue

        # Validate source integrity
        if allocation.award_id != locked_award.id:
            raise DealSourceIntegrityError(
                f"Allocation '{allocation.id}' award mismatch with locked award."
            )
        if allocation.offer.rfq_id != locked_rfq.id:
            raise DealSourceIntegrityError(
                f"Allocation offer '{allocation.offer_id}' RFQ mismatch with award RFQ."
            )
        if allocation.offer_version.offer_id != allocation.offer_id:
            raise DealSourceIntegrityError(
                f"Allocation offer_version '{allocation.offer_version_id}' does not belong to Offer '{allocation.offer_id}'."
            )
        if allocation.offer_version_id != allocation.offer_version.id:
            raise DealSourceIntegrityError("Allocation offer_version reference mismatch.")
        if locked_award.rfq_id != locked_rfq.id:
            raise DealSourceIntegrityError("Award RFQ reference mismatch.")

        # Derive Buyer strictly from RFQ owning Organization
        buyer_org = locked_rfq.organization

        # Derive Seller strictly from Offer economic party
        offer = allocation.offer
        if offer.offering_organization_id:
            seller_org = offer.offering_organization
            seller_ext = None
        elif offer.external_counterparty_id:
            seller_org = None
            seller_ext = offer.external_counterparty
        else:
            raise DealSourceIntegrityError(
                f"Offer '{offer.id}' has neither offering_organization nor external_counterparty."
            )

        # Create Deal identity
        Deal.objects.create(
            award=locked_award,
            award_allocation=allocation,
            rfq=locked_rfq,
            offer=offer,
            offer_version=allocation.offer_version,
            buyer_organization=buyer_org,
            seller_organization=seller_org,
            seller_external_counterparty=seller_ext,
            created_by=actor,
        )
        newly_created = True

    # 8. Load and return all Deals for the Award
    all_deals = list(
        Deal.objects.filter(award=locked_award)
        .select_related(
            "award",
            "award_allocation",
            "rfq",
            "offer",
            "offer_version",
            "buyer_organization",
            "seller_organization",
            "seller_external_counterparty",
            "created_by",
        )
        .order_by("award_allocation__created_at", "award_allocation__id")
    )

    return all_deals, newly_created

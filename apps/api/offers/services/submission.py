from decimal import Decimal
from typing import Any, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from commodities.services import validate_commodity_payload
from offers.enums import LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    OfferVersionNotFoundError,
    StaleVersionError,
)
from offers.models import Offer, OfferVersion
from organizations.models import (
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus
from trade_hub.models.invitation import RFQInvitation, RFQInvitationStatus
from trade_hub.services.rfq_lifecycle import RFQLifecycleService
from trade_hub.services.visibility_service import RFQVisibilityService


def _validate_expected_version(offer: Offer, expected_version: Any) -> None:
    """
    Validates optimistic concurrency aggregate_version on Offer.
    Raises InvalidVersionError if malformed or non-positive.
    Raises StaleVersionError if expected_version != offer.aggregate_version.
    """
    if expected_version is None:
        return
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if offer.aggregate_version != expected_version:
        raise StaleVersionError(
            f"Stale version error: Offer aggregate_version is {offer.aggregate_version}, "
            f"expected {expected_version}."
        )


def _extract_version_id(version_or_id: Any) -> uuid.UUID:
    if isinstance(version_or_id, OfferVersion):
        return version_or_id.pk
    if isinstance(version_or_id, uuid.UUID):
        return version_or_id
    if isinstance(version_or_id, str):
        try:
            return uuid.UUID(version_or_id)
        except (ValueError, AttributeError) as exc:
            raise OfferVersionNotFoundError(f"Invalid OfferVersion ID: '{version_or_id}'.") from exc
    raise OfferValidationError(f"Invalid OfferVersion identifier: '{version_or_id}'.")


def submit_internal_offer_version(
    *,
    actor: Any,
    offer_version: OfferVersion | uuid.UUID | str,
    expected_version: Optional[int] = None,
    require_expected_version: bool = False,
) -> OfferVersion:
    """
    Authoritative domain service to submit an internal Supplier or Broker OfferVersion (T0803).

    Workflow:
    authorized Organization member
    -> own Offer
    -> Draft OfferVersion
    -> submit
    -> immutable Submitted version
    -> RFQ Collecting Offers

    Lock Hierarchy & Concurrency:
    Exclusive row locks are acquired strictly in the order:
        1. RFQ (parent container / state holder)
        2. Offer (aggregate root)
        3. OfferVersion (draft commercial proposal)
    This strictly prevents deadlock with RFQ lifecycle actions (publish, close, cancel)
    which also lock RFQ first.

    Validations enforced at action time:
    - Actor authentication and active membership in exactly the offering organization.
    - Membership role: Owner, Manager, Member allowed; Viewer denied (read-only).
    - Economic party: internal platform organization only (external counterparties rejected; T0804 owns external).
    - Capability revalidation: SUPPLIER requires active Supplier capability; BROKER requires active Broker capability.
    - Participation revalidation: reuse Epic 5 authoritative visibility & participation rules.
      Private RFQs require active invitation; buyer cannot submit offers to own RFQ.
    - RFQ state: must be Published or Collecting Offers.
    - Deadline: server clock timezone-aware check; no late submissions.
    - Optimistic concurrency: expected_version verified against Offer.aggregate_version.
    - Draft status: must be in DRAFT (already SUBMITTED raises controlled conflict).
    - Revalidation: exact RFQ schema lock (never active schema), positive quantity, compatible unit,
      positive price, 3-letter currency, delivery dates, logistics consistency, child cost components.

    Transitions:
    - OfferVersion: DRAFT -> SUBMITTED (immutable).
    - Actor/timestamp: submitted_by = actor, submitted_at = timezone.now().
    - Offer: current_submitted_version = version, aggregate_version += 1.
    - RFQ: if Published -> Collecting Offers (via RFQLifecycleService.start_collecting_offers).
    - RFQInvitation: if active invitation in INVITED/VIEWED, marks RESPONDED.
    """
    # 1. Actor Authentication check
    if not actor or not getattr(actor, "is_authenticated", False):
        raise OfferPermissionDeniedError("Authentication is required to submit an offer version.")

    # 2. Resolve version identifier and metadata without locks
    target_version_id = _extract_version_id(offer_version)
    version_meta = (
        OfferVersion.objects.filter(pk=target_version_id)
        .values(
            "id",
            "offer_id",
            "offer__rfq_id",
            "offer__offering_organization_id",
            "offer__external_counterparty_id",
        )
        .first()
    )
    if not version_meta:
        raise OfferVersionNotFoundError(f"OfferVersion '{target_version_id}' does not exist.")

    # External counterparty guard (T0804 explicitly owns external path)
    if version_meta["offer__external_counterparty_id"] is not None:
        raise OfferValidationError(
            "External counterparty offers cannot be submitted via internal supplier/broker flow."
        )

    rfq_id = version_meta["offer__rfq_id"]
    offer_id = version_meta["offer_id"]

    # 3. Transaction with Strict Lock Hierarchy (RFQ -> Offer -> OfferVersion)
    with transaction.atomic():
        # 3.1 Lock RFQ first
        try:
            locked_rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferValidationError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        # 3.2 Lock Offer second
        try:
            locked_offer = Offer.objects.select_for_update().get(pk=offer_id)
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.") from exc

        # 3.3 Lock Draft OfferVersion third
        try:
            locked_draft = OfferVersion.objects.select_for_update().get(
                pk=target_version_id, offer_id=locked_offer.id
            )
        except OfferVersion.DoesNotExist as exc:
            raise OfferVersionNotFoundError(
                f"OfferVersion '{target_version_id}' does not exist for Offer '{locked_offer.id}'."
            ) from exc


        # 4. Verify Internal Organization Economic Party
        if locked_offer.offering_organization_id is None or not locked_offer.offering_organization:
            raise OfferValidationError(
                "Offer does not belong to an internal platform organization."
            )
        if not locked_offer.offering_organization.is_active:
            raise OfferValidationError(
                f"Organization '{locked_offer.offering_organization.name}' is inactive."
            )

        # Owning Buyer Organization cannot submit offer to own RFQ
        if locked_rfq.organization_id == locked_offer.offering_organization_id:
            raise OfferValidationError(
                "Owning buyer organization cannot submit an offer for its own RFQ."
            )

        # 5. Verify Actor Active Membership & Allowed Roles
        membership = OrganizationMembership.objects.filter(
            user=actor,
            organization_id=locked_offer.offering_organization_id,
            is_active=True,
            organization__is_active=True,
        ).first()
        if not membership:
            raise OfferPermissionDeniedError(
                "Actor does not have active membership in the offering organization."
            )

        if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
            raise OfferPermissionDeniedError(
                "Viewers have read-only access and cannot submit offers."
            )
        if membership.role not in [
            OrganizationMembership.OrganizationRole.OWNER,
            OrganizationMembership.OrganizationRole.MANAGER,
            OrganizationMembership.OrganizationRole.MEMBER,
        ]:
            raise OfferPermissionDeniedError(
                f"Role '{membership.role}' is not authorized to submit offers."
            )

        # 6. Revalidate Capability at Submission Time
        if locked_offer.offeror_role == OfferorRole.SUPPLIER:
            has_capability = OrganizationCapability.objects.filter(
                organization_id=locked_offer.offering_organization_id,
                capability=OrganizationCapability.CapabilityType.SUPPLIER,
            ).exists()
            if not has_capability:
                raise OfferValidationError(
                    f"Organization '{locked_offer.offering_organization.name}' lacks required Supplier capability."
                )
        elif locked_offer.offeror_role == OfferorRole.BROKER:
            has_capability = OrganizationCapability.objects.filter(
                organization_id=locked_offer.offering_organization_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists()
            if not has_capability:
                raise OfferValidationError(
                    f"Organization '{locked_offer.offering_organization.name}' lacks required Broker capability."
                )
        else:
            raise OfferValidationError(
                f"Invalid offeror role '{locked_offer.offeror_role}'. Must be SUPPLIER or BROKER."
            )

        # 7. Check RFQ State
        if locked_rfq.status not in [RFQStatus.PUBLISHED, RFQStatus.COLLECTING_OFFERS]:
            raise OfferStateError(
                f"Target RFQ is in status '{locked_rfq.status}'. Offers can only be submitted against "
                f"Published or Collecting Offers RFQs."
            )

        # 8. Check RFQ Deadline
        if locked_rfq.submission_deadline and timezone.now() > locked_rfq.submission_deadline:
            raise OfferValidationError("RFQ offer submission deadline has passed.")

        # 9. Revalidate RFQ Participation & Visibility (Epic 5 Rules)
        if not RFQVisibilityService.is_rfq_visible(
            locked_rfq, actor, organization=locked_offer.offering_organization
        ):
            raise OfferPermissionDeniedError(
                "Target RFQ is not visible or accessible to the offering organization."
            )


        # 10. Optimistic Concurrency Check
        if require_expected_version and expected_version is None:
            raise InvalidVersionError("expected_version is required.")
        _validate_expected_version(locked_offer, expected_version)

        # 11. Draft Status Check (Double-submission race guard)
        if locked_draft.status != OfferVersionStatus.DRAFT:
            raise OfferConflictError(
                f"OfferVersion {locked_draft.version_number} is already in status "
                f"'{locked_draft.status}' and cannot be submitted again."
            )

        # 12. Revalidate Commercial & Specification Payload
        # Dynamic specifications must match exact RFQ schema_version (never current active schema)
        if locked_draft.schema_version_id != locked_rfq.schema_version_id:
            raise OfferValidationError(
                "OfferVersion schema_version must match the target RFQ schema_version."
            )
        try:
            validate_commodity_payload(
                locked_rfq.schema_version, locked_draft.specifications or {}
            )
        except ValidationError as exc:
            raise OfferValidationError(
                f"Dynamic specifications failed schema validation upon submission: {exc}"
            ) from exc

        # Quantity strictly positive
        if locked_draft.offered_quantity is None or locked_draft.offered_quantity <= Decimal("0"):
            raise OfferValidationError("Offered quantity must be positive.")

        # Unit compatibility
        rfq_unit = (locked_rfq.unit or "").strip().upper()
        offer_unit = (locked_draft.quantity_unit or "").strip().upper()
        if not offer_unit:
            raise OfferValidationError("quantity_unit is required.")
        if rfq_unit and offer_unit != rfq_unit:
            raise OfferValidationError(
                f"Offer quantity unit '{locked_draft.quantity_unit}' is incompatible with RFQ unit '{locked_rfq.unit}'."
            )

        # Unit price strictly positive
        if locked_draft.unit_price is None or locked_draft.unit_price <= Decimal("0"):
            raise OfferValidationError("Unit price must be positive.")

        # Currency 3-letter code
        clean_curr = (locked_draft.currency or "").strip().upper()
        if len(clean_curr) != 3:
            raise OfferValidationError("currency must be a valid 3-letter ISO code.")

        # Delivery window consistency
        if (
            locked_draft.delivery_start
            and locked_draft.delivery_end
            and locked_draft.delivery_start > locked_draft.delivery_end
        ):
            raise OfferValidationError("delivery_start cannot be after delivery_end.")

        # Logistics consistency
        clean_logistics = (
            locked_draft.logistics_cost_status or LogisticsCostStatus.UNKNOWN
        ).strip()
        if clean_logistics not in LogisticsCostStatus.values:
            raise OfferValidationError(
                f"Invalid logistics_cost_status: '{locked_draft.logistics_cost_status}'."
            )
        if clean_logistics == LogisticsCostStatus.KNOWN_SEPARATE:
            if locked_draft.logistics_cost_amount is None:
                raise OfferValidationError(
                    "logistics_cost_amount is required when logistics_cost_status is KNOWN_SEPARATE."
                )
            if locked_draft.logistics_cost_amount < Decimal("0"):
                raise OfferValidationError("logistics_cost_amount cannot be negative.")
        else:
            if locked_draft.logistics_cost_amount is not None:
                raise OfferValidationError(
                    f"logistics_cost_amount must be absent when logistics_cost_status is {clean_logistics}."
                )

        # Child cost components consistency
        for comp in locked_draft.cost_components.all():
            if comp.currency != clean_curr:
                raise OfferValidationError(
                    f"Cost component currency '{comp.currency}' must match "
                    f"OfferVersion currency '{clean_curr}'."
                )
            if comp.amount <= Decimal("0"):
                raise OfferValidationError("Cost component amount must be positive.")

        # 13. Execute DRAFT -> SUBMITTED Transition
        now = timezone.now()
        locked_draft.status = OfferVersionStatus.SUBMITTED
        locked_draft.submitted_by = actor
        locked_draft.submitted_at = now
        locked_draft.save()

        # 14. Advance current_submitted_version Pointer & Increment aggregate_version
        locked_offer.current_submitted_version = locked_draft
        locked_offer.aggregate_version += 1
        locked_offer.save(
            update_fields=["current_submitted_version", "aggregate_version", "updated_at"]
        )

        # 15. Transition RFQ from Published to Collecting Offers
        if locked_rfq.status == RFQStatus.PUBLISHED:
            RFQLifecycleService.start_collecting_offers(locked_rfq, actor=actor)

        # 16. Update RFQInvitation to RESPONDED if applicable
        invitation = RFQInvitation.objects.filter(
            rfq=locked_rfq,
            organization_id=locked_offer.offering_organization_id,
            status__in=[RFQInvitationStatus.INVITED, RFQInvitationStatus.VIEWED],
        ).first()
        if invitation:
            invitation.status = RFQInvitationStatus.RESPONDED
            invitation.responded_at = now
            invitation.save(update_fields=["status", "responded_at", "updated_at"])

    return locked_draft

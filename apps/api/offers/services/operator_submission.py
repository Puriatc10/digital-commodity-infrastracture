from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from identity.models import SystemRoleAssignment
from offers.enums import LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    StaleVersionError,
)
from offers.models import Offer, OfferVersion
from offers.services.version_services import create_draft_offer_version
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from trade_hub.models import RFQ, RFQStatus
from trade_hub.services.rfq_lifecycle import RFQLifecycleService


def _is_operator_or_product_admin(user: Any) -> bool:
    """
    Verify whether user holds active Operator or Product Admin system authority.

    Invariant:
    Conferred strictly by SystemRoleAssignment(OPERATOR or ADMIN).
    Django is_staff and is_superuser alone grant NO product operational authority.
    """
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


def _validate_expected_version(offer: Offer, expected_version: Any) -> None:
    """Validate optimistic concurrency version against parent Offer aggregate_version."""
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


def _extract_id(obj_or_id: Any, error_class: type[Exception], entity_name: str) -> uuid.UUID:
    if hasattr(obj_or_id, "id"):
        return obj_or_id.id
    if hasattr(obj_or_id, "pk"):
        return obj_or_id.pk
    if isinstance(obj_or_id, uuid.UUID):
        return obj_or_id
    if isinstance(obj_or_id, str):
        try:
            return uuid.UUID(obj_or_id)
        except (ValueError, AttributeError) as exc:
            raise error_class(f"Invalid {entity_name} ID: '{obj_or_id}'.") from exc
    raise error_class(f"Invalid {entity_name} identifier: '{obj_or_id}'.")


def submit_operator_external_offer(
    *,
    actor: Any,
    rfq: RFQ | uuid.UUID | str,
    opportunity: Opportunity | uuid.UUID | str,
    offered_quantity: Decimal | str,
    quantity_unit: str,
    unit_price: Decimal | str,
    currency: str = "USD",
    payment_terms: str = "",
    delivery_terms: str = "",
    incoterm: str = "",
    delivery_start: Optional[date] = None,
    delivery_end: Optional[date] = None,
    valid_until: Optional[datetime] = None,
    logistics_cost_status: str = LogisticsCostStatus.UNKNOWN,
    logistics_cost_amount: Optional[Decimal | str] = None,
    specifications: Optional[dict] = None,
    notes: str = "",
    cost_components: Optional[list[dict[str, Any]]] = None,
    external_counterparty: Optional[ExternalCounterparty | uuid.UUID | str] = None,
    expected_version: Optional[int] = None,
) -> tuple[Offer, OfferVersion]:
    """
    Authoritative domain service for Operator Submission on Behalf (T0804 / T0611).

    Executes the pilot-critical workflow:
        Qualified Supply Opportunity
        -> ExternalCounterparty (economic party)
        -> Operator explicit action (entering actor)
        -> RFQ Offer (aggregate root)
        -> Submitted OfferVersion (immutable commercial snapshot)
        -> RFQ Collecting Offers (lifecycle transition)

    Critical Invariants:
    1. Authorization: strictly Operator or Product Admin (SystemRoleAssignment).
       Django is_staff, is_superuser, Buyer, Supplier, Broker organizations are denied.
    2. Atomic Lock Hierarchy:
       Acquires exclusive row locks strictly in order:
           1. RFQ (parent negotiation context)
           2. Opportunity (source provenance lead)
           3. Offer (aggregate root when resolving existing thread)
    3. Opportunity Validation:
       - Must have direction = SUPPLY (Demand rejected).
       - Must be in QUALIFIED status.
       - Must have external_counterparty (internal organization leads rejected).
    4. Counterparty Derivation:
       - Economic party is derived strictly from the source Opportunity's external_counterparty.
       - Caller cannot spoof or substitute an unrelated ExternalCounterparty.
    5. Offer Role:
       - Fixed to SUPPLIER for external supplier quotes.
       - Broker referral attribution is preserved on Opportunity, NOT made economic party.
       - No fake User, Organization, or Membership is created.
    6. RFQ Lifecycle & Deadline:
       - RFQ must be in PUBLISHED or COLLECTING_OFFERS.
       - Submission deadline is strictly enforced (no late override for Operator/Admin).
    7. Schema Lock & Validation:
       - Specifications validated against RFQ.schema_version (never current active schema).
       - Commercial terms strictly validated (positive quantity, price, unit compatibility).
    8. Thread Uniqueness & Existing Version Guard:
       - Reuses existing (rfq, external_counterparty, SUPPLIER) Offer parent if present.
       - If current_submitted_version already exists, rejects safely rather than bypassing
         T0810/T0811 revision workflow.
    9. Transaction Atomicity & Rollback:
       - All operations execute in a single atomic transaction. Injected failure rolls back
         Offer, OfferVersion, pointer mutation, and RFQ transition completely.
    """
    # 1. Strict Actor Authorization (SystemRoleAssignment)
    if not _is_operator_or_product_admin(actor):
        raise OfferPermissionDeniedError(
            "Only platform Operators and Product Admins may submit offers on behalf of external counterparties."
        )

    rfq_id = _extract_id(rfq, OfferValidationError, "RFQ")

    # Opportunity identifier can be a UUID or human-readable identifier (e.g. OPP-2026-000124)
    if isinstance(opportunity, Opportunity):
        opp_id = opportunity.pk
    elif isinstance(opportunity, uuid.UUID):
        opp_id = opportunity
    elif isinstance(opportunity, str):
        try:
            opp_id = uuid.UUID(opportunity)
        except ValueError:
            # String identifier (OPP-...)
            opp_obj = Opportunity.objects.filter(identifier=opportunity).values("id").first()
            if not opp_obj:
                raise OfferNotFoundError(f"Source Opportunity '{opportunity}' does not exist.")
            opp_id = opp_obj["id"]
    else:
        raise OfferValidationError(f"Invalid Opportunity identifier: '{opportunity}'.")

    # Optional caller-supplied counterparty ID validation
    caller_cp_id: Optional[uuid.UUID] = None
    if external_counterparty is not None:
        caller_cp_id = _extract_id(external_counterparty, OfferValidationError, "ExternalCounterparty")

    # 2. Atomic Transaction with Strict Lock Order
    with transaction.atomic():
        # 2.1 Lock RFQ first
        try:
            locked_rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferNotFoundError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        # RFQ Status Check: only Published or Collecting Offers accept offers
        if locked_rfq.status not in [RFQStatus.PUBLISHED, RFQStatus.COLLECTING_OFFERS]:
            raise OfferStateError(
                f"Target RFQ is in status '{locked_rfq.status}'. Offers can only be submitted against "
                f"Published or Collecting Offers RFQs."
            )

        # RFQ Deadline Check: server clock timezone-aware check; no late override for anyone
        if locked_rfq.submission_deadline and timezone.now() > locked_rfq.submission_deadline:
            raise OfferValidationError("RFQ offer submission deadline has passed.")

        # 2.2 Lock Opportunity second
        try:
            locked_opp = Opportunity.objects.select_for_update().get(pk=opp_id)
        except Opportunity.DoesNotExist as exc:
            raise OfferNotFoundError(f"Source Opportunity '{opp_id}' does not exist.") from exc

        # Validate Opportunity Direction: strictly SUPPLY
        if locked_opp.direction != OpportunityDirection.SUPPLY:
            raise OfferValidationError(
                f"Source Opportunity direction must be SUPPLY (found '{locked_opp.direction}')."
            )

        # Validate Opportunity Status: strictly QUALIFIED
        if locked_opp.status != OpportunityStatus.QUALIFIED:
            raise OfferStateError(
                f"Source Opportunity must be in Qualified status to submit an external offer "
                f"(current status: '{locked_opp.status}')."
            )

        # Validate Opportunity Counterparty: must be off-platform ExternalCounterparty
        if locked_opp.external_counterparty_id is None or locked_opp.organization_id is not None:
            raise OfferValidationError(
                "Source Opportunity must belong to an off-platform ExternalCounterparty."
            )

        # Counterparty Derivation: derived strictly from source Opportunity
        derived_cp = locked_opp.external_counterparty

        # Reject caller attempt to substitute an unrelated ExternalCounterparty
        if caller_cp_id is not None and caller_cp_id != derived_cp.id:
            raise OfferValidationError(
                f"Caller-supplied external counterparty '{caller_cp_id}' does not match "
                f"the source Opportunity's external counterparty '{derived_cp.id}'."
            )

        # 2.3 Resolve or Create Offer Parent Aggregate
        # Identity: (rfq, external_counterparty, SUPPLIER)
        locked_offer = (
            Offer.objects.select_for_update()
            .filter(
                rfq=locked_rfq,
                external_counterparty=derived_cp,
                offeror_role=OfferorRole.SUPPLIER,
            )
            .first()
        )

        if locked_offer is not None:
            # Reusing existing parent thread
            _validate_expected_version(locked_offer, expected_version)

            # Invariant: If a submitted version already exists, never overwrite or mutate it.
            # Next version requires revision workflow (T0810/T0811); fail safely to prevent bypass.
            if locked_offer.current_submitted_version_id is not None:
                raise OfferConflictError(
                    f"An offer version has already been submitted for RFQ '{locked_rfq.id}' "
                    f"and external counterparty '{derived_cp.id}'. Subsequent versions require revision workflow."
                )

            # Check if an unsubmitted draft already exists
            existing_draft = OfferVersion.objects.filter(
                offer=locked_offer, status=OfferVersionStatus.DRAFT
            ).first()
            if existing_draft is not None:
                raise OfferConflictError(
                    f"Offer '{locked_offer.id}' already has an active draft (version {existing_draft.version_number})."
                )
        else:
            # Create new parent Offer aggregate under lock
            try:
                locked_offer = Offer.objects.create(
                    rfq=locked_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=None,
                    external_counterparty=derived_cp,
                    source_opportunity=locked_opp,
                    aggregate_version=1,
                    created_by=actor,
                )
            except IntegrityError as exc:
                raise OfferConflictError(
                    "An offer thread already exists for this RFQ, external counterparty, and role."
                ) from exc

        # 2.4 Allocate and Create DRAFT OfferVersion using T0802 service
        # This revalidates:
        # - schema lock to locked_rfq.schema_version (never active schema)
        # - dynamic specifications via validate_commodity_payload
        # - offered_quantity > 0, unit compatibility with RFQ
        # - unit_price > 0, 3-letter currency
        # - delivery dates, logistics consistency, child cost components
        draft_version = create_draft_offer_version(
            actor=actor,
            offer=locked_offer,
            offered_quantity=offered_quantity,
            quantity_unit=quantity_unit,
            unit_price=unit_price,
            currency=currency,
            payment_terms=payment_terms,
            delivery_terms=delivery_terms,
            incoterm=incoterm,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            valid_until=valid_until,
            logistics_cost_status=logistics_cost_status,
            logistics_cost_amount=logistics_cost_amount,
            specifications=specifications if specifications is not None else (locked_opp.specifications or {}),
            notes=notes,
            cost_components=cost_components,
        )

        # 2.5 Authoritative Submission Transition (DRAFT -> SUBMITTED)
        now = timezone.now()
        draft_version.status = OfferVersionStatus.SUBMITTED
        draft_version.submitted_by = actor
        draft_version.submitted_at = now
        draft_version.save()

        # Advance parent Offer pointer and aggregate version
        locked_offer.refresh_from_db()
        locked_offer.current_submitted_version = draft_version
        locked_offer.aggregate_version += 1
        locked_offer.save(
            update_fields=["current_submitted_version", "aggregate_version", "updated_at"]
        )

        # 2.6 Transition RFQ from Published to Collecting Offers
        if locked_rfq.status == RFQStatus.PUBLISHED:
            RFQLifecycleService.start_collecting_offers(locked_rfq, actor=actor)

    return locked_offer, draft_version

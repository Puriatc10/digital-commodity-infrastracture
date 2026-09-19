import copy
from decimal import Decimal
from typing import Any, List, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from commodities.services import validate_commodity_payload
from identity.models import SystemRoleAssignment
from offers.enums import (
    FORBIDDEN_REVISION_FIELDS,
    LogisticsCostStatus,
    OfferorRole,
    OfferVersionStatus,
    RevisionRequestedField,
    RevisionRequestStatus,
)
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    OfferVersionNotFoundError,
    RevisionRequestNotFoundError,
    StaleVersionError,
)
from offers.models import Offer, OfferCostComponent, OfferVersion, RevisionRequest
from organizations.models import (
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus
from trade_hub.services.rfq_lifecycle import RFQLifecycleService


def is_operator_or_admin(user: Any) -> bool:
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


def is_buyer_procurement_actor(user: Any, rfq: RFQ) -> bool:
    """
    Verify whether user is an authorized procurement actor of the RFQ's owning Buyer organization.

    Allowed:
    - Active Owner or Manager of the RFQ's owning Buyer organization with active BUYER capability.
    Denied:
    - Member or Viewer.
    - Foreign Buyer organizations.
    - Suppliers and Brokers.
    """
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False

    has_capability = OrganizationCapability.objects.filter(
        organization_id=rfq.organization_id,
        capability=OrganizationCapability.CapabilityType.BUYER,
    ).exists()
    if not has_capability:
        return False

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id=rfq.organization_id,
        is_active=True,
        organization__is_active=True,
    ).first()
    if not membership:
        return False

    return membership.role in (
        OrganizationMembership.OrganizationRole.OWNER,
        OrganizationMembership.OrganizationRole.MANAGER,
    )


def _validate_expected_version(offer: Offer, expected_version: Any) -> None:
    """
    Validate optimistic concurrency aggregate_version on Offer.
    Raises InvalidVersionError if missing, malformed, or non-positive.
    Raises StaleVersionError if expected_version != offer.aggregate_version.
    """
    if expected_version is None:
        raise InvalidVersionError("expected_version is required.")
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


def _validate_requested_fields(requested_fields: Any) -> List[str]:
    """
    Validates canonical requested_fields list against allowed commercial fields.
    Rejects duplicates, non-string items, empty lists, and forbidden server fields.
    """
    if not isinstance(requested_fields, list):
        raise OfferValidationError("requested_fields must be a list of field identifiers.")
    if not requested_fields:
        raise OfferValidationError("At least one field must be requested for revision.")

    allowed = set(RevisionRequestedField.values)
    seen = set()
    cleaned = []
    for f in requested_fields:
        if not isinstance(f, str):
            raise OfferValidationError(f"Invalid field identifier '{f}'; expected string.")
        clean_f = f.strip()
        if not clean_f:
            raise OfferValidationError("requested_fields cannot contain blank entries.")
        if clean_f in seen:
            raise OfferValidationError(f"Duplicate field '{clean_f}' in requested_fields.")
        seen.add(clean_f)
        if clean_f in FORBIDDEN_REVISION_FIELDS:
            raise OfferValidationError(
                f"Field '{clean_f}' is a server-owned attribute and cannot be requested for revision."
            )
        if clean_f not in allowed:
            raise OfferValidationError(
                f"Field '{clean_f}' is not an authorized revisable field. "
                f"Allowed fields: {', '.join(sorted(allowed))}."
            )
        cleaned.append(clean_f)
    return cleaned


def _extract_uuid(val: Any, entity_name: str, error_cls: type[Exception]) -> uuid.UUID:
    if hasattr(val, "id"):
        return val.id
    if hasattr(val, "pk"):
        return val.pk
    if isinstance(val, uuid.UUID):
        return val
    if isinstance(val, str):
        try:
            return uuid.UUID(val)
        except (ValueError, AttributeError) as exc:
            raise error_cls(f"Invalid {entity_name} ID: '{val}'.") from exc
    raise error_cls(f"Invalid {entity_name} identifier: '{val}'.")


def create_revision_request(
    *,
    actor: Any,
    offer: Offer | uuid.UUID | str,
    base_offer_version: OfferVersion | uuid.UUID | str,
    requested_fields: List[str],
    message: str = "",
    expected_version: Any,
) -> RevisionRequest:
    """
    Authoritative domain service to open a RevisionRequest against an Offer (T0810, Contract §56-§59).

    Execution Steps under strict lock hierarchy (RFQ -> Offer -> OfferVersion):
    1. Resolve identifiers without locks.
    2. Begin atomic transaction.
    3. Lock RFQ row.
    4. Lock Offer aggregate root row.
    5. Lock base OfferVersion row.
    6. Validate actor authorization (Buyer procurement actor or Operator/Product Admin).
    7. Validate expected_version against Offer.aggregate_version.
    8. Validate RFQ lifecycle (reject terminal states Closed, Cancelled, Awarded).
    9. Validate base_offer_version belongs to Offer, is SUBMITTED, and matches current_submitted_version.
    10. Validate no existing OPEN revision request for this Offer.
    11. Validate requested_fields canonical items.
    12. Create RevisionRequest in OPEN status.
    13. Increment Offer.aggregate_version += 1.
    14. If RFQ is in Collecting Offers, transition to Negotiating via RFQLifecycleService.start_negotiating.
    15. Commit atomically.

    Guarantees:
    - Commercial immutability: base_offer_version fields are never mutated.
    - Human agency: human-created action only; no automated DecisionRun triggers.
    """
    # 1. Resolve IDs
    offer_id = _extract_uuid(offer, "Offer", OfferNotFoundError)
    base_ver_id = _extract_uuid(base_offer_version, "OfferVersion", OfferVersionNotFoundError)

    # 2. Validate requested fields before acquiring locks
    clean_fields = _validate_requested_fields(requested_fields)
    clean_message = message.strip() if message else ""

    # Pre-fetch Offer to find parent RFQ ID
    offer_meta = Offer.objects.filter(pk=offer_id).values("id", "rfq_id").first()
    if not offer_meta:
        raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.")
    rfq_id = offer_meta["rfq_id"]

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

        # 3.3 Lock base OfferVersion third
        try:
            locked_base = OfferVersion.objects.select_for_update().get(
                pk=base_ver_id, offer_id=locked_offer.id
            )
        except OfferVersion.DoesNotExist as exc:
            raise OfferVersionNotFoundError(
                f"OfferVersion '{base_ver_id}' does not exist for Offer '{locked_offer.id}'."
            ) from exc

        # 4. Authorize Actor
        is_op_admin = is_operator_or_admin(actor)
        is_buyer = is_buyer_procurement_actor(actor, locked_rfq)
        if not (is_op_admin or is_buyer):
            raise OfferPermissionDeniedError(
                "Only authorized Buyer procurement actors (Owner/Manager) or platform Operators "
                "may request revisions on this RFQ."
            )

        # 5. Validate expected_version
        _validate_expected_version(locked_offer, expected_version)

        # 6. Verify RFQ Lifecycle State
        if locked_rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
            raise OfferStateError(
                f"Cannot request revision on RFQ in terminal status '{locked_rfq.status}'."
            )

        # 7. Verify Base Version Integrity
        if locked_base.status != OfferVersionStatus.SUBMITTED:
            raise OfferValidationError(
                f"Cannot request revision against OfferVersion in status '{locked_base.status}'. "
                "Only submitted versions can serve as a revision base."
            )

        if locked_offer.current_submitted_version_id != locked_base.id:
            current_num = (
                locked_offer.current_submitted_version.version_number
                if locked_offer.current_submitted_version
                else "none"
            )
            raise OfferConflictError(
                f"Base OfferVersion V{locked_base.version_number} is stale. "
                f"Current submitted version is V{current_num}."
            )

        # 8. Verify No OPEN Request Exists (Application-level check)
        if RevisionRequest.objects.filter(
            offer=locked_offer, status=RevisionRequestStatus.OPEN
        ).exists():
            raise OfferConflictError(
                f"An open revision request already exists for Offer '{locked_offer.id}'."
            )

        # 9. Create OPEN RevisionRequest
        try:
            revision_request = RevisionRequest.objects.create(
                offer=locked_offer,
                base_offer_version=locked_base,
                requested_fields=clean_fields,
                message=clean_message,
                requested_by=actor,
                status=RevisionRequestStatus.OPEN,
            )
        except IntegrityError as exc:
            raise OfferConflictError(
                f"An open revision request already exists for Offer '{locked_offer.id}'."
            ) from exc

        # 10. Increment Offer aggregate_version
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

        # 11. Transition RFQ: Collecting Offers -> Negotiating
        if locked_rfq.status == RFQStatus.COLLECTING_OFFERS:
            RFQLifecycleService.start_negotiating(locked_rfq, actor=actor)

        return revision_request


def decline_revision_request(
    *,
    actor: Any,
    revision_request: RevisionRequest | uuid.UUID | str,
    expected_version: Any,
) -> RevisionRequest:
    """
    Authoritative domain service for an Offer participant to decline an open RevisionRequest (T0810).

    Workflow:
    - Internal: Authorized member of the offering organization (Owner, Manager, Member; Viewer denied).
    - External: Operator / Product Admin acting on behalf of external counterparty.
    - Buyer / foreign competitors CANNOT decline.

    Transitions:
    - RevisionRequest: OPEN -> DECLINED, resolved_at = now.
    - Offer: aggregate_version += 1.
    """
    req_id = _extract_uuid(revision_request, "RevisionRequest", RevisionRequestNotFoundError)

    req_meta = (
        RevisionRequest.objects.filter(pk=req_id)
        .values(
            "id",
            "offer_id",
            "offer__rfq_id",
            "offer__offering_organization_id",
            "offer__external_counterparty_id",
        )
        .first()
    )
    if not req_meta:
        raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.")

    rfq_id = req_meta["offer__rfq_id"]
    offer_id = req_meta["offer_id"]
    offering_org_id = req_meta["offer__offering_organization_id"]
    external_cp_id = req_meta["offer__external_counterparty_id"]

    with transaction.atomic():
        # Lock RFQ -> Offer -> RevisionRequest
        try:
            RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferValidationError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        try:
            locked_offer = Offer.objects.select_for_update().get(pk=offer_id)
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.") from exc

        try:
            locked_req = RevisionRequest.objects.select_for_update().get(
                pk=req_id, offer_id=locked_offer.id
            )
        except RevisionRequest.DoesNotExist as exc:
            raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.") from exc

        # 1. Authorize Actor representing the Offer Economic Party
        if external_cp_id is not None:
            # External offer: Operator or Product Admin
            if not is_operator_or_admin(actor):
                raise OfferPermissionDeniedError(
                    "Only platform Operators or Product Admins may decline revision requests "
                    "for external counterparty offers."
                )
        else:
            # Internal offer: authorized member of offering organization
            if not actor or not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
                raise OfferPermissionDeniedError("Authentication required.")

            membership = OrganizationMembership.objects.filter(
                user=actor,
                organization_id=offering_org_id,
                is_active=True,
                organization__is_active=True,
            ).first()
            if not membership:
                raise OfferPermissionDeniedError(
                    "Actor is not an active member of the offering organization."
                )
            if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
                raise OfferPermissionDeniedError("Viewers have read-only access and cannot decline revisions.")
            if membership.role not in (
                OrganizationMembership.OrganizationRole.OWNER,
                OrganizationMembership.OrganizationRole.MANAGER,
                OrganizationMembership.OrganizationRole.MEMBER,
            ):
                raise OfferPermissionDeniedError(
                    f"Role '{membership.role}' is not authorized to decline revisions."
                )

        # 2. Concurrency verification against Offer aggregate_version
        _validate_expected_version(locked_offer, expected_version)

        # 3. Status Check: Must be OPEN
        if locked_req.status != RevisionRequestStatus.OPEN:
            raise OfferConflictError(
                f"RevisionRequest {locked_req.id} is in status '{locked_req.status}' "
                "and cannot be declined."
            )

        # 4. Transition to DECLINED
        now = timezone.now()
        locked_req.status = RevisionRequestStatus.DECLINED
        locked_req.resolved_at = now
        locked_req.save(update_fields=["status", "resolved_at", "updated_at"])

        # 5. Increment Offer aggregate_version
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

        return locked_req


def cancel_revision_request(
    *,
    actor: Any,
    revision_request: RevisionRequest | uuid.UUID | str,
    expected_version: Any,
) -> RevisionRequest:
    """
    Authoritative domain service for a Buyer or Operator to cancel an open RevisionRequest (T0810).

    Workflow:
    - Buyer-side authorized procurement actor (Owner/Manager of RFQ Buyer org).
    - Platform Operator or Product Admin.
    - Offer participants (Supplier/Broker) CANNOT cancel Buyer's request.

    Transitions:
    - RevisionRequest: OPEN -> CANCELLED, resolved_at = now.
    - Offer: aggregate_version += 1.
    """
    req_id = _extract_uuid(revision_request, "RevisionRequest", RevisionRequestNotFoundError)

    req_meta = (
        RevisionRequest.objects.filter(pk=req_id)
        .values("id", "offer_id", "offer__rfq_id")
        .first()
    )
    if not req_meta:
        raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.")

    rfq_id = req_meta["offer__rfq_id"]
    offer_id = req_meta["offer_id"]

    with transaction.atomic():
        # Lock RFQ -> Offer -> RevisionRequest
        try:
            locked_rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferValidationError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        try:
            locked_offer = Offer.objects.select_for_update().get(pk=offer_id)
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.") from exc

        try:
            locked_req = RevisionRequest.objects.select_for_update().get(
                pk=req_id, offer_id=locked_offer.id
            )
        except RevisionRequest.DoesNotExist as exc:
            raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.") from exc

        # 1. Authorize Actor (Buyer procurement actor or Operator/Product Admin)
        is_op_admin = is_operator_or_admin(actor)
        is_buyer = is_buyer_procurement_actor(actor, locked_rfq)
        if not (is_op_admin or is_buyer):
            raise OfferPermissionDeniedError(
                "Only authorized Buyer procurement actors (Owner/Manager) or platform Operators "
                "may cancel revision requests on this RFQ."
            )

        # 2. Concurrency verification against Offer aggregate_version
        _validate_expected_version(locked_offer, expected_version)

        # 3. Status Check: Must be OPEN
        if locked_req.status != RevisionRequestStatus.OPEN:
            raise OfferConflictError(
                f"RevisionRequest {locked_req.id} is in status '{locked_req.status}' "
                "and cannot be cancelled."
            )

        # 4. Transition to CANCELLED
        now = timezone.now()
        locked_req.status = RevisionRequestStatus.CANCELLED
        locked_req.resolved_at = now
        locked_req.save(update_fields=["status", "resolved_at", "updated_at"])

        # 5. Increment Offer aggregate_version
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

        return locked_req


def authorize_offer_actor(
    *,
    actor: Any,
    offer: Offer,
    rfq: RFQ,
    action_name: str = "revise offer",
) -> None:
    """
    Authoritative actor authorization for Offer actions (T0803, T0804, T0811).
    - If external counterparty: Operator or Product Admin only.
    - If internal organization: Active Owner, Manager, or Member with verified capability (SUPPLIER or BROKER).
      Viewer denied. Non-member denied. Buyer organization denied submitting or revising an offer on own RFQ.
    """
    if not actor or not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
        raise OfferPermissionDeniedError("Authentication is required.")

    if offer.external_counterparty_id is not None:
        if not is_operator_or_admin(actor):
            raise OfferPermissionDeniedError(
                f"Only platform Operators and Product Admins may {action_name} on behalf of external counterparties."
            )
        return

    # Internal organization
    if not offer.offering_organization_id:
        raise OfferValidationError("Offer does not specify an economic party.")

    if not offer.offering_organization or not offer.offering_organization.is_active:
        raise OfferValidationError(
            f"Organization '{offer.offering_organization.name if offer.offering_organization else offer.offering_organization_id}' is inactive."
        )

    # Buyer cannot act as offeror on own RFQ
    if rfq.organization_id == offer.offering_organization_id:
        raise OfferValidationError(
            "Owning buyer organization cannot submit or revise an offer for its own RFQ."
        )

    membership = OrganizationMembership.objects.filter(
        user=actor,
        organization_id=offer.offering_organization_id,
        is_active=True,
        organization__is_active=True,
    ).first()
    if not membership:
        raise OfferPermissionDeniedError(
            "Actor does not have active membership in the offering organization."
        )

    if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
        raise OfferPermissionDeniedError(
            f"Viewers have read-only access and cannot {action_name}."
        )

    if membership.role not in (
        OrganizationMembership.OrganizationRole.OWNER,
        OrganizationMembership.OrganizationRole.MANAGER,
        OrganizationMembership.OrganizationRole.MEMBER,
    ):
        raise OfferPermissionDeniedError(
            f"Role '{membership.role}' is not authorized to {action_name}."
        )

    # Revalidate Capability
    if offer.offeror_role == OfferorRole.SUPPLIER:
        has_cap = OrganizationCapability.objects.filter(
            organization_id=offer.offering_organization_id,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        ).exists()
        if not has_cap:
            raise OfferValidationError(
                f"Organization '{offer.offering_organization.name}' lacks required Supplier capability."
            )
    elif offer.offeror_role == OfferorRole.BROKER:
        has_cap = OrganizationCapability.objects.filter(
            organization_id=offer.offering_organization_id,
            capability=OrganizationCapability.CapabilityType.BROKER,
        ).exists()
        if not has_cap:
            raise OfferValidationError(
                f"Organization '{offer.offering_organization.name}' lacks required Broker capability."
            )
    else:
        raise OfferValidationError(
            f"Invalid offeror role '{offer.offeror_role}'. Must be SUPPLIER or BROKER."
        )


def create_revised_draft_offer_version(
    *,
    actor: Any,
    revision_request: RevisionRequest | uuid.UUID | str,
    expected_version: Any,
    offer: Optional[Offer | uuid.UUID | str] = None,
) -> OfferVersion:
    """
    Authoritative domain service to create a DRAFT OfferVersion from an OPEN RevisionRequest (T0811).

    Lock Order (strict global hierarchy):
        1. RFQ
        2. Offer
        3. RevisionRequest
        4. base OfferVersion

    Validations under lock:
        - request.status == OPEN
        - request.offer == Offer
        - request.base_offer_version == Offer.current_submitted_version
        - base OfferVersion.status == SUBMITTED
        - expected_version matches Offer.aggregate_version
        - No active draft already exists on Offer (one draft per offer invariant)
        - RFQ status allows negotiation (PUBLISHED, COLLECTING_OFFERS, NEGOTIATING) & deadline not passed
        - Actor authorized (Operator for external; active Owner/Manager/Member with capability for internal)

    Copy Semantics:
        - Sequential server-allocated version_number = max(existing) + 1
        - Schema version locked to exact RFQ.schema_version (never active schema lookup, no payload migration)
        - Deep copy dynamic specifications dict (preventing mutable reference sharing with V1)
        - Commercial fields copied: offered_quantity, quantity_unit, unit_price, currency,
          payment_terms, delivery_terms, incoterm, delivery_start, delivery_end, valid_until,
          logistics_cost_status, logistics_cost_amount, notes
        - Server identity/lifecycle fields NOT copied: status=DRAFT, created_by=actor, submitted_by=None, submitted_at=None
        - Deep copy child OfferCostComponent rows into new instances referencing new draft

    Aggregate State Mutation:
        - Increments Offer.aggregate_version += 1
        - Does NOT modify Offer.current_submitted_version
        - Does NOT modify RevisionRequest.status (remains OPEN)
    """
    req_id = _extract_uuid(revision_request, "RevisionRequest", RevisionRequestNotFoundError)

    req_meta = (
        RevisionRequest.objects.filter(pk=req_id)
        .values("id", "offer_id", "offer__rfq_id", "base_offer_version_id")
        .first()
    )
    if not req_meta:
        raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.")

    rfq_id = req_meta["offer__rfq_id"]
    offer_id = req_meta["offer_id"]
    base_ver_id = req_meta["base_offer_version_id"]

    if offer is not None:
        passed_offer_id = _extract_uuid(offer, "Offer", OfferNotFoundError)
        if passed_offer_id != offer_id:
            raise OfferValidationError("RevisionRequest does not belong to the specified Offer.")

    with transaction.atomic():
        # 1. Lock RFQ
        try:
            locked_rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferValidationError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        # 2. Lock Offer
        try:
            locked_offer = Offer.objects.select_for_update().get(pk=offer_id)
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.") from exc

        # 3. Lock RevisionRequest
        try:
            locked_req = RevisionRequest.objects.select_for_update().get(
                pk=req_id, offer_id=locked_offer.id
            )
        except RevisionRequest.DoesNotExist as exc:
            raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.") from exc

        # 4. Lock base OfferVersion
        try:
            locked_base = OfferVersion.objects.select_for_update().get(
                pk=base_ver_id, offer_id=locked_offer.id
            )
        except OfferVersion.DoesNotExist as exc:
            raise OfferVersionNotFoundError(
                f"Base OfferVersion '{base_ver_id}' does not exist for Offer '{locked_offer.id}'."
            ) from exc

        # Authorize Actor
        authorize_offer_actor(
            actor=actor,
            offer=locked_offer,
            rfq=locked_rfq,
            action_name="create a revised draft",
        )

        # Optimistic concurrency check
        _validate_expected_version(locked_offer, expected_version)

        # RFQ Lifecycle Check
        if locked_rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
            raise OfferStateError(
                f"Cannot create revised draft on RFQ in terminal status '{locked_rfq.status}'."
            )
        if locked_rfq.submission_deadline and timezone.now() > locked_rfq.submission_deadline:
            raise OfferValidationError("RFQ offer submission deadline has passed.")

        # RevisionRequest status check
        if locked_req.status != RevisionRequestStatus.OPEN:
            raise OfferConflictError(
                f"RevisionRequest {locked_req.id} is in status '{locked_req.status}' and cannot create a revised draft (must be OPEN)."
            )

        # Base version check
        if locked_base.status != OfferVersionStatus.SUBMITTED:
            raise OfferValidationError(
                f"Base OfferVersion V{locked_base.version_number} is in status '{locked_base.status}'. "
                "Only SUBMITTED versions can serve as a revision base."
            )

        # Stale base check against current submitted version
        if locked_offer.current_submitted_version_id != locked_base.id:
            current_num = (
                locked_offer.current_submitted_version.version_number
                if locked_offer.current_submitted_version
                else "none"
            )
            raise OfferConflictError(
                f"Revision request base version V{locked_base.version_number} is stale. "
                f"Current submitted version is V{current_num}."
            )

        # One active draft per offer invariant
        existing_draft = OfferVersion.objects.filter(
            offer=locked_offer, status=OfferVersionStatus.DRAFT
        ).first()
        if existing_draft:
            raise OfferConflictError(
                f"Offer '{locked_offer.id}' already has an active draft (version {existing_draft.version_number})."
            )

        # Sequential Version Number Allocation
        max_v = (
            OfferVersion.objects.filter(offer=locked_offer).aggregate(
                models.Max("version_number")
            )["version_number__max"]
            or 0
        )
        allocated_version_number = max_v + 1

        # Deep copy specifications to guarantee isolated object state
        specs_copy = copy.deepcopy(locked_base.specifications or {})

        # Create new DRAFT OfferVersion
        try:
            new_draft = OfferVersion.objects.create(
                offer=locked_offer,
                version_number=allocated_version_number,
                status=OfferVersionStatus.DRAFT,
                schema_version=locked_rfq.schema_version,
                specifications=specs_copy,
                offered_quantity=locked_base.offered_quantity,
                quantity_unit=locked_base.quantity_unit,
                unit_price=locked_base.unit_price,
                currency=locked_base.currency,
                payment_terms=locked_base.payment_terms,
                delivery_terms=locked_base.delivery_terms,
                incoterm=locked_base.incoterm,
                delivery_start=locked_base.delivery_start,
                delivery_end=locked_base.delivery_end,
                valid_until=locked_base.valid_until,
                logistics_cost_status=locked_base.logistics_cost_status,
                logistics_cost_amount=locked_base.logistics_cost_amount,
                notes=locked_base.notes,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise OfferConflictError(
                f"Concurrent draft creation conflict on Offer '{locked_offer.id}': {exc}"
            ) from exc

        # Deep copy child OfferCostComponent rows
        for comp in locked_base.cost_components.all():
            OfferCostComponent.objects.create(
                offer_version=new_draft,
                kind=comp.kind,
                amount=comp.amount,
                currency=comp.currency,
                description=comp.description,
            )

        # Increment Offer aggregate_version
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

        return new_draft


def submit_revised_offer_version(
    *,
    actor: Any,
    revision_request: RevisionRequest | uuid.UUID | str,
    expected_version: Any,
    draft_version: Optional[OfferVersion | uuid.UUID | str] = None,
) -> tuple[OfferVersion, RevisionRequest]:
    """
    Authoritative domain service to submit a revised OfferVersion and atomically resolve
    the associated OPEN RevisionRequest (T0811).

    Lock Order (strict global hierarchy):
        1. RFQ
        2. Offer
        3. RevisionRequest
        4. OfferVersion(s) (ordered by version_number: base first, then draft)

    Validations immediately before submit:
        - RevisionRequest is OPEN
        - request.base_offer_version == Offer.current_submitted_version (stale base check)
        - Draft belongs to Offer and is in DRAFT status
        - Draft version_number is expected sequential next version (> base.version_number)
        - expected_version matches Offer.aggregate_version
        - RFQ status in [PUBLISHED, COLLECTING_OFFERS, NEGOTIATING] & deadline not passed
        - Actor authorized (Operator for external; active Owner/Manager/Member with capability for internal)
        - Commercial payload revalidated against RFQ.schema_version

    Atomic State Transitions:
        - draft.status = SUBMITTED, submitted_by = actor, submitted_at = now
        - Offer.current_submitted_version = draft, aggregate_version += 1
        - RevisionRequest.status = RESOLVED, resolved_by_version = draft, resolved_at = now
        - All committed in a single transaction; failure triggers complete rollback
    """
    req_id = _extract_uuid(revision_request, "RevisionRequest", RevisionRequestNotFoundError)

    req_meta = (
        RevisionRequest.objects.filter(pk=req_id)
        .values("id", "offer_id", "offer__rfq_id", "base_offer_version_id")
        .first()
    )
    if not req_meta:
        raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.")

    rfq_id = req_meta["offer__rfq_id"]
    offer_id = req_meta["offer_id"]
    base_ver_id = req_meta["base_offer_version_id"]

    draft_ver_id = (
        _extract_uuid(draft_version, "OfferVersion", OfferVersionNotFoundError)
        if draft_version is not None
        else None
    )

    with transaction.atomic():
        # 1. Lock RFQ
        try:
            locked_rfq = RFQ.objects.select_for_update().get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise OfferValidationError(f"Target RFQ '{rfq_id}' does not exist.") from exc

        # 2. Lock Offer
        try:
            locked_offer = Offer.objects.select_for_update().get(pk=offer_id)
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_id}' does not exist.") from exc

        # 3. Lock RevisionRequest
        try:
            locked_req = RevisionRequest.objects.select_for_update().get(
                pk=req_id, offer_id=locked_offer.id
            )
        except RevisionRequest.DoesNotExist as exc:
            raise RevisionRequestNotFoundError(f"RevisionRequest '{req_id}' does not exist.") from exc

        # 4. Lock OfferVersion(s) ordered by version_number (base first, then draft)
        # If draft_ver_id not provided, resolve the active draft for this offer
        if draft_ver_id is None:
            active_draft = OfferVersion.objects.filter(
                offer=locked_offer, status=OfferVersionStatus.DRAFT
            ).first()
            if not active_draft:
                raise OfferVersionNotFoundError(
                    f"Offer '{locked_offer.id}' does not have an active draft to submit."
                )
            draft_ver_id = active_draft.id

        versions_to_lock = list(
            OfferVersion.objects.select_for_update()
            .filter(pk__in=[base_ver_id, draft_ver_id], offer_id=locked_offer.id)
            .order_by("version_number")
        )

        locked_base = next((v for v in versions_to_lock if v.pk == base_ver_id), None)
        if not locked_base:
            raise OfferVersionNotFoundError(
                f"Base OfferVersion '{base_ver_id}' does not exist for Offer '{locked_offer.id}'."
            )

        locked_draft = next((v for v in versions_to_lock if v.pk == draft_ver_id), None)
        if not locked_draft:
            raise OfferVersionNotFoundError(
                f"Draft OfferVersion '{draft_ver_id}' does not exist for Offer '{locked_offer.id}'."
            )

        # Authorize Actor
        authorize_offer_actor(
            actor=actor,
            offer=locked_offer,
            rfq=locked_rfq,
            action_name="submit revised offer",
        )

        # Optimistic concurrency check
        _validate_expected_version(locked_offer, expected_version)

        # RFQ Lifecycle Check
        if locked_rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
            raise OfferStateError(
                f"Cannot submit revised offer on RFQ in terminal status '{locked_rfq.status}'."
            )
        if locked_rfq.submission_deadline and timezone.now() > locked_rfq.submission_deadline:
            raise OfferValidationError("RFQ offer submission deadline has passed.")

        # RevisionRequest status check
        if locked_req.status != RevisionRequestStatus.OPEN:
            raise OfferConflictError(
                f"RevisionRequest {locked_req.id} is in status '{locked_req.status}' and cannot be resolved (must be OPEN)."
            )

        # Base version check
        if locked_base.status != OfferVersionStatus.SUBMITTED:
            raise OfferValidationError(
                f"Base OfferVersion V{locked_base.version_number} is in status '{locked_base.status}'. "
                "Only SUBMITTED versions can serve as a revision base."
            )

        # Stale base check against current submitted version
        if locked_offer.current_submitted_version_id != locked_base.id:
            current_num = (
                locked_offer.current_submitted_version.version_number
                if locked_offer.current_submitted_version
                else "none"
            )
            raise OfferConflictError(
                f"Revision request base version V{locked_base.version_number} is stale. "
                f"Current submitted version is V{current_num}."
            )

        # Draft status and relationship checks
        if locked_draft.offer_id != locked_offer.id:
            raise OfferValidationError("Draft does not belong to this Offer.")

        if locked_draft.status != OfferVersionStatus.DRAFT:
            raise OfferConflictError(
                f"OfferVersion {locked_draft.version_number} is in status '{locked_draft.status}' "
                "and cannot be submitted (already submitted)."
            )

        if locked_draft.version_number <= locked_base.version_number:
            raise OfferValidationError(
                f"Draft version number V{locked_draft.version_number} must be greater than base version V{locked_base.version_number}."
            )

        # Revalidate dynamic commodity specifications against exact RFQ schema_version
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

        # Revalidate quantity
        if locked_draft.offered_quantity is None or locked_draft.offered_quantity <= Decimal("0"):
            raise OfferValidationError("Offered quantity must be positive.")

        # Revalidate unit compatibility
        rfq_unit = (locked_rfq.unit or "").strip().upper()
        offer_unit = (locked_draft.quantity_unit or "").strip().upper()
        if not offer_unit:
            raise OfferValidationError("quantity_unit is required.")
        if rfq_unit and offer_unit != rfq_unit:
            raise OfferValidationError(
                f"Offer quantity unit '{locked_draft.quantity_unit}' is incompatible with RFQ unit '{locked_rfq.unit}'."
            )

        # Revalidate unit price
        if locked_draft.unit_price is None or locked_draft.unit_price <= Decimal("0"):
            raise OfferValidationError("Unit price must be positive.")

        # Revalidate currency
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

        # Atomic Execution
        now = timezone.now()

        # 1. Submit Draft OfferVersion
        locked_draft.status = OfferVersionStatus.SUBMITTED
        locked_draft.submitted_by = actor
        locked_draft.submitted_at = now
        locked_draft.save()

        # 2. Advance Offer pointer and increment aggregate_version
        locked_offer.current_submitted_version = locked_draft
        locked_offer.aggregate_version += 1
        locked_offer.save(
            update_fields=["current_submitted_version", "aggregate_version", "updated_at"]
        )

        # 3. Resolve RevisionRequest
        locked_req.status = RevisionRequestStatus.RESOLVED
        locked_req.resolved_by_version = locked_draft
        locked_req.resolved_at = now
        locked_req.save(
            update_fields=["status", "resolved_by_version", "resolved_at", "updated_at"]
        )

        return (locked_draft, locked_req)


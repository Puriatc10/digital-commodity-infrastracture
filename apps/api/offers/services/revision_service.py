from typing import Any, List
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from identity.models import SystemRoleAssignment
from offers.enums import (
    FORBIDDEN_REVISION_FIELDS,
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
from offers.models import Offer, OfferVersion, RevisionRequest
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

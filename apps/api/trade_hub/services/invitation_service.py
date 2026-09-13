import datetime
from typing import Any
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.exceptions import (
    DuplicateInvitationError,
    InvalidInvitationStatusError,
    InvalidTransitionError,
    InviteeIneligibleError,
    InvitationNotFoundError,
    InvitationPermissionDeniedError,
    RFQNotFoundError,
)
from trade_hub.models import RFQ, RFQInvitation, RFQInvitationStatus, RFQStatus
from trade_hub.services.visibility_service import (
    has_global_visibility,
    resolve_authoritative_organization,
)


def _extract_uuid(
    val: Any, error_class: type[Exception] = RFQNotFoundError, label: str = "ID"
) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    if hasattr(val, "pk") and isinstance(val.pk, uuid.UUID):
        return val.pk
    if isinstance(val, str):
        try:
            return uuid.UUID(val)
        except (ValueError, AttributeError) as exc:
            raise error_class(f"Invalid {label}: '{val}'") from exc
    raise error_class(f"Invalid {label} representation: '{val}'")


def is_operator_or_admin(user: Any) -> bool:
    """Check if user holds OPERATOR or ADMIN system role."""
    return has_global_visibility(user)


def can_manage_rfq_invitations(
    user: Any, rfq: RFQ, organization_hint: Any = None
) -> bool:
    """
    Check if the user is authorized to manage invitations for the RFQ.
    Allowed:
    - Platform Operator or Product Admin (via SystemRoleAssignment).
    - Owner or Manager of the RFQ's owning Buyer organization.
    Denied:
    - Member or Viewer of the RFQ's owning organization.
    - Foreign organizations.
    - Invited Suppliers or Brokers.
    - Django staff/superuser alone without system roles.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_operator_or_admin(user):
        return True

    # Must have active Owner or Manager membership in the RFQ's owning organization
    current_org = resolve_authoritative_organization(user, organization_hint)
    if current_org is None or current_org.pk != rfq.organization_id:
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


def can_decline_invitation(
    user: Any, invitation: RFQInvitation, organization_hint: Any = None
) -> bool:
    """
    Check if the user is authorized to decline an invitation.
    Allowed:
    - Platform Operator or Product Admin.
    - Owner or Manager of the invited organization.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_operator_or_admin(user):
        return True

    current_org = resolve_authoritative_organization(user, organization_hint)
    if current_org is None or current_org.pk != invitation.organization_id:
        return False

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id=invitation.organization_id,
        is_active=True,
        organization__is_active=True,
    ).first()
    if not membership:
        return False

    return membership.role in (
        OrganizationMembership.OrganizationRole.OWNER,
        OrganizationMembership.OrganizationRole.MANAGER,
    )


def can_view_invitation(
    user: Any, invitation: RFQInvitation, organization_hint: Any = None
) -> bool:
    """
    Check if the user is authorized to view an invitation.
    Allowed:
    - Platform Operator or Product Admin.
    - Any active member of the RFQ owning Buyer organization.
    - Any active member of the invited organization.
    Competitor/foreign orgs are strictly denied.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_operator_or_admin(user):
        return True

    current_org = resolve_authoritative_organization(user, organization_hint)
    if current_org is None:
        return False

    if current_org.pk in (invitation.rfq.organization_id, invitation.organization_id):
        return OrganizationMembership.objects.filter(
            user=user,
            organization_id=current_org.pk,
            is_active=True,
            organization__is_active=True,
        ).exists()

    return False


def validate_invitee_eligibility(rfq: RFQ, target_org: Organization) -> None:
    """
    Validate that an organization is eligible to receive an RFQ invitation.
    - Must be active.
    - Cannot be the RFQ's owning organization (no self-invite).
    - Must possess Supplier or Broker capability.
    - Cannot be Buyer-only.
    """
    if not target_org.is_active:
        raise InviteeIneligibleError(
            f"Target organization '{target_org.name}' is inactive."
        )

    if target_org.pk == rfq.organization_id:
        raise InviteeIneligibleError(
            "Cannot invite the RFQ owning organization (self-invitation prohibited)."
        )

    capabilities = set(
        OrganizationCapability.objects.filter(
            organization=target_org,
        ).values_list("capability", flat=True)
    )
    has_supplier_or_broker = bool(
        capabilities
        & {
            OrganizationCapability.CapabilityType.SUPPLIER,
            OrganizationCapability.CapabilityType.BROKER,
        }
    )
    if not has_supplier_or_broker:
        raise InviteeIneligibleError(
            f"Target organization '{target_org.name}' is ineligible: must possess Supplier or Broker capability."
        )


class RFQInvitationService:
    """Authoritative domain service governing RFQ invitations, lifecycle, and privacy."""

    @staticmethod
    @transaction.atomic
    def create_invitation(
        rfq_or_id: Any,
        target_org_or_id: Any,
        user: Any,
        *,
        organization_hint: Any = None,
        expires_at: datetime.datetime | None = None,
    ) -> RFQInvitation:
        """
        Invite an organization (Supplier or Broker) to an RFQ.
        - Synchronizes with concurrent RFQ lifecycle changes via select_for_update.
        - Strictly rejects invitations on Closed or Cancelled RFQs.
        - Strictly enforces Owner/Manager or Operator authorization.
        - Strictly enforces invitee eligibility (Supplier/Broker, no self-invite).
        - Prevents duplicate invitations atomically using PostgreSQL unique constraint.
        """
        rfq_id = _extract_uuid(rfq_or_id, RFQNotFoundError, "RFQ ID")
        target_org_id = _extract_uuid(
            target_org_or_id, InviteeIneligibleError, "Organization ID"
        )

        # Exclusive lock on RFQ to synchronize with concurrent close/cancel
        try:
            rfq = (
                RFQ.objects.select_for_update()
                .select_related("organization")
                .get(pk=rfq_id)
            )
        except RFQ.DoesNotExist as exc:
            raise RFQNotFoundError(f"RFQ with id '{rfq_id}' does not exist.") from exc

        # Check RFQ lifecycle boundary
        if rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED):
            raise InvalidTransitionError(
                f"Cannot invite participants to an RFQ in status '{rfq.status}'."
            )

        # Authorize actor
        if not can_manage_rfq_invitations(user, rfq, organization_hint):
            raise InvitationPermissionDeniedError(
                "User lacks permission to invite participants to this RFQ."
            )

        # Retrieve target organization
        try:
            target_org = Organization.objects.get(pk=target_org_id)
        except Organization.DoesNotExist as exc:
            raise InviteeIneligibleError(
                f"Target organization with id '{target_org_id}' does not exist."
            ) from exc

        # Validate eligibility
        validate_invitee_eligibility(rfq, target_org)

        # Check for existing duplicate invitation
        if RFQInvitation.objects.filter(rfq=rfq, organization=target_org).exists():
            raise DuplicateInvitationError(
                f"Organization '{target_org.name}' is already invited to this RFQ."
            )

        # Record provenance
        operator_flag = is_operator_or_admin(user)
        if operator_flag:
            # Check if operator is also an active member of buyer org
            current_org = resolve_authoritative_organization(user, organization_hint)
            if current_org and current_org.pk == rfq.organization_id:
                operator_flag = False

        try:
            invitation = RFQInvitation.objects.create(
                rfq=rfq,
                organization=target_org,
                status=RFQInvitationStatus.INVITED,
                invited_by=user if getattr(user, "is_authenticated", False) else None,
                invited_by_operator=operator_flag,
                expires_at=expires_at,
            )
        except IntegrityError as exc:
            raise DuplicateInvitationError(
                f"Organization '{target_org.name}' is already invited to this RFQ."
            ) from exc

        return invitation

    @staticmethod
    @transaction.atomic
    def mark_invitation_viewed(
        invitation_or_id: Any,
        user: Any,
        *,
        organization_hint: Any = None,
    ) -> RFQInvitation:
        """
        Mark an invitation as viewed when the invited organization views the RFQ.
        Only advances status from 'invited' to 'viewed'.
        """
        inv_id = _extract_uuid(
            invitation_or_id, InvitationNotFoundError, "Invitation ID"
        )

        try:
            invitation = (
                RFQInvitation.objects.select_for_update()
                .select_related("rfq", "organization")
                .get(pk=inv_id)
            )
        except RFQInvitation.DoesNotExist as exc:
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist."
            ) from exc

        if not can_view_invitation(user, invitation, organization_hint):
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist or is not accessible."
            )

        if invitation.status == RFQInvitationStatus.INVITED:
            invitation.status = RFQInvitationStatus.VIEWED
            invitation.viewed_at = timezone.now()
            invitation.save(update_fields=["status", "viewed_at", "updated_at"])

        return invitation

    @staticmethod
    @transaction.atomic
    def decline_invitation(
        invitation_or_id: Any,
        user: Any,
        *,
        reason: str = "",
        organization_hint: Any = None,
    ) -> RFQInvitation:
        """
        Decline an invitation.
        Permitted only to Owner/Manager of the invited organization or Platform Operator.
        Revokes Private RFQ visibility for the declining organization.
        """
        inv_id = _extract_uuid(
            invitation_or_id, InvitationNotFoundError, "Invitation ID"
        )

        try:
            invitation = (
                RFQInvitation.objects.select_for_update()
                .select_related("rfq", "organization")
                .get(pk=inv_id)
            )
        except RFQInvitation.DoesNotExist as exc:
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist."
            ) from exc

        if not can_view_invitation(user, invitation, organization_hint):
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist or is not accessible."
            )

        if not can_decline_invitation(user, invitation, organization_hint):
            raise InvitationPermissionDeniedError(
                "Only Owner or Manager of the invited organization can decline an invitation."
            )

        if invitation.status == RFQInvitationStatus.DECLINED:
            return invitation

        if invitation.status == RFQInvitationStatus.EXPIRED:
            raise InvalidInvitationStatusError("Cannot decline an expired invitation.")

        invitation.status = RFQInvitationStatus.DECLINED
        invitation.declined_at = timezone.now()
        invitation.decline_reason = str(reason).strip() if reason else ""
        invitation.save(
            update_fields=["status", "declined_at", "decline_reason", "updated_at"]
        )

        return invitation

    @staticmethod
    def list_rfq_invitations(
        rfq_or_id: Any,
        user: Any,
        *,
        organization_hint: Any = None,
    ) -> Any:
        """
        List all participants/invitations for an RFQ.
        Strictly restricted to Buyer Owner/Manager or Platform Operator.
        Invited suppliers/brokers cannot enumerate competitors and are denied with 403.
        """
        rfq_id = _extract_uuid(rfq_or_id, RFQNotFoundError, "RFQ ID")

        try:
            rfq = RFQ.objects.get(pk=rfq_id)
        except RFQ.DoesNotExist as exc:
            raise RFQNotFoundError(f"RFQ with id '{rfq_id}' does not exist.") from exc

        if not can_manage_rfq_invitations(user, rfq, organization_hint):
            raise InvitationPermissionDeniedError(
                "Only the RFQ buyer organization or platform operators can view the participant list."
            )

        return (
            RFQInvitation.objects.filter(rfq=rfq)
            .select_related("organization", "invited_by", "rfq")
            .prefetch_related(
                "organization__capabilities",
                "organization__commodities__commodity",
            )
        )

    @staticmethod
    def get_own_invitation(
        rfq_or_id: Any,
        user: Any,
        *,
        organization_hint: Any = None,
    ) -> RFQInvitation:
        """
        Retrieve the invitee organization's own invitation record for an RFQ.
        Guarantees competitor isolation: returns only the caller's organization invitation.
        """
        rfq_id = _extract_uuid(rfq_or_id, RFQNotFoundError, "RFQ ID")
        current_org = resolve_authoritative_organization(user, organization_hint)
        if current_org is None:
            raise InvitationNotFoundError("No active organization context found.")

        try:
            return RFQInvitation.objects.select_related(
                "organization", "invited_by", "rfq"
            ).get(rfq_id=rfq_id, organization=current_org)
        except RFQInvitation.DoesNotExist as exc:
            raise InvitationNotFoundError(
                f"No invitation found for organization '{current_org.name}' on RFQ '{rfq_id}'."
            ) from exc

    @staticmethod
    def get_invitation_detail(
        invitation_or_id: Any,
        user: Any,
        *,
        organization_hint: Any = None,
    ) -> RFQInvitation:
        """
        Retrieve detail of a specific invitation.
        Access granted only to:
        - Buyer Owner/Manager (owns the RFQ)
        - Invitee Organization members (the invited counterparty)
        - Platform Operator / Product Admin
        Competitors receive 404 (hidden resource semantics).
        """
        inv_id = _extract_uuid(
            invitation_or_id, InvitationNotFoundError, "Invitation ID"
        )

        try:
            invitation = RFQInvitation.objects.select_related(
                "organization", "invited_by", "rfq"
            ).get(pk=inv_id)
        except RFQInvitation.DoesNotExist as exc:
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist."
            ) from exc

        if not can_view_invitation(user, invitation, organization_hint):
            raise InvitationNotFoundError(
                f"Invitation with id '{inv_id}' does not exist or is not accessible."
            )

        return invitation


# Module-level convenience functions
create_invitation = RFQInvitationService.create_invitation
mark_invitation_viewed = RFQInvitationService.mark_invitation_viewed
decline_invitation = RFQInvitationService.decline_invitation
list_rfq_invitations = RFQInvitationService.list_rfq_invitations
get_own_invitation = RFQInvitationService.get_own_invitation
get_invitation_detail = RFQInvitationService.get_invitation_detail

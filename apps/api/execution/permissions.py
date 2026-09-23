from typing import Any, Optional

from rest_framework import permissions

from execution.exceptions import ExecutionPermissionDeniedError
from identity.models import SystemRoleAssignment
from organizations.models import OrganizationMembership


def is_operator_or_admin(user: Any) -> bool:
    """
    Verify if user holds OPERATOR or ADMIN system authority via SystemRoleAssignment.

    Invariant:
    - Django staff/superuser alone confers NO product authority.
    - User must be authenticated and active.
    - User must have an explicit SystemRoleAssignment for OPERATOR or ADMIN.
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


def check_workflow_management_authority(user: Any) -> None:
    """
    Ensure the actor possesses internal operator or product admin authority.

    Raises:
        ExecutionPermissionDeniedError if authorization check fails.
    """
    if not is_operator_or_admin(user):
        raise ExecutionPermissionDeniedError(
            "Workflow definition management is strictly restricted to Platform Operators and Product Admins."
        )


def check_execution_read_access(user: Any, deal_or_execution: Any) -> None:
    """
    Verify read authorization for an Execution aggregate or its Deal.

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active members of the Deal's Buyer Organization (any membership role, including Viewer).
    - Active members of the Deal's Seller Organization (if internal seller).

    Denied:
    - Anonymous users.
    - Django staff/superusers lacking an explicit SystemRoleAssignment.
    - Attributed-only brokers (attribution is provenance, not authorization).
    - Unrelated organizations / competitor participants.
    - External counterparties (handled exclusively via Operator).
    """
    deal = getattr(deal_or_execution, "deal", deal_or_execution)
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise ExecutionPermissionDeniedError("Authentication required.")

    if is_operator_or_admin(user):
        return

    allowed_org_ids = [deal.buyer_organization_id]
    if deal.seller_organization_id:
        allowed_org_ids.append(deal.seller_organization_id)

    is_party_member = OrganizationMembership.objects.filter(
        user=user,
        organization_id__in=allowed_org_ids,
        is_active=True,
        organization__is_active=True,
    ).exists()

    if not is_party_member:
        raise ExecutionPermissionDeniedError("You do not have permission to access this execution.")


def check_execution_mutation_access(
    user: Any,
    deal_or_execution: Any,
    milestone_code: Optional[str] = None,
) -> None:
    """
    Verify mutation authorization for an Execution or a specific Milestone transition.

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active non-viewer members (Owner, Manager, Member) of the authorized side.

    Denied:
    - Anonymous users.
    - Django staff/superusers without SystemRoleAssignment.
    - Viewer role members (strictly read-only).
    - Attributed-only brokers.
    - Buyer attempting seller-exclusive milestone actions.
    - Seller attempting buyer-exclusive milestone actions.
    - Unrelated organizations.
    """
    deal = getattr(deal_or_execution, "deal", deal_or_execution)
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise ExecutionPermissionDeniedError("Authentication required.")

    if is_operator_or_admin(user):
        return

    allowed_org_ids = [deal.buyer_organization_id]
    if deal.seller_organization_id:
        allowed_org_ids.append(deal.seller_organization_id)

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id__in=allowed_org_ids,
        is_active=True,
        organization__is_active=True,
    ).first()

    if not membership:
        raise ExecutionPermissionDeniedError("You do not have permission to mutate this execution.")

    if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
        raise ExecutionPermissionDeniedError("Viewer role is read-only and cannot mutate execution state.")

    if milestone_code:
        is_buyer = membership.organization_id == deal.buyer_organization_id
        is_seller = deal.seller_organization_id and (membership.organization_id == deal.seller_organization_id)

        # Operational milestone ownership matrix (Epic 10 Contract §80, §81)
        SELLER_ONLY_MILESTONES = {"LOADING_SCHEDULED", "LOADED", "IN_TRANSIT"}
        BUYER_ONLY_MILESTONES = {"ACCEPTED"}

        if is_buyer and milestone_code in SELLER_ONLY_MILESTONES:
            raise ExecutionPermissionDeniedError(
                f"Milestone '{milestone_code}' can only be updated by the Seller or Operator."
            )

        if is_seller and milestone_code in BUYER_ONLY_MILESTONES:
            raise ExecutionPermissionDeniedError(
                f"Milestone '{milestone_code}' can only be updated by the Buyer or Operator."
            )


def check_logistics_mutation_authority(
    user: Any,
    deal_or_execution: Any,
    action_type: str,
) -> None:
    """
    Verify side-specific operational logistics mutation authority (Epic 10 Contract §77–§82, T1004).

    Operational actions:
    - Seller operational actions:
      SCHEDULE_LOADING, RECORD_LOADING, UPDATE_TRANSPORT, UPDATE_ETA, UPDATE_COST
    - Buyer operational actions:
      RECORD_DELIVERY

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active non-viewer members (Owner, Manager, Member) of the authorized side.

    Denied:
    - Anonymous users.
    - Django staff/superusers without SystemRoleAssignment.
    - Viewer role members (strictly read-only).
    - Attributed-only brokers.
    - Buyer attempting seller operational actions.
    - Seller attempting buyer delivery recording.
    - External counterparty direct sessions (handled exclusively via Operator).
    - Unrelated organizations.
    """
    deal = getattr(deal_or_execution, "deal", deal_or_execution)
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise ExecutionPermissionDeniedError("Authentication required.")

    if is_operator_or_admin(user):
        return

    allowed_org_ids = [deal.buyer_organization_id]
    if deal.seller_organization_id:
        allowed_org_ids.append(deal.seller_organization_id)

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id__in=allowed_org_ids,
        is_active=True,
        organization__is_active=True,
    ).first()

    if not membership:
        raise ExecutionPermissionDeniedError("You do not have permission to mutate logistics for this execution.")

    if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
        raise ExecutionPermissionDeniedError("Viewer role is read-only and cannot mutate execution state.")

    is_buyer = membership.organization_id == deal.buyer_organization_id
    is_seller = bool(deal.seller_organization_id and (membership.organization_id == deal.seller_organization_id))

    SELLER_ACTIONS = {
        "SCHEDULE_LOADING",
        "RECORD_LOADING",
        "UPDATE_TRANSPORT",
        "UPDATE_ETA",
        "UPDATE_COST",
    }
    BUYER_ACTIONS = {
        "RECORD_DELIVERY",
    }

    if is_buyer and action_type in SELLER_ACTIONS:
        raise ExecutionPermissionDeniedError(
            f"Logistics action '{action_type}' can only be performed by the Seller or Operator."
        )

    if is_seller and action_type in BUYER_ACTIONS:
        raise ExecutionPermissionDeniedError(
            f"Logistics action '{action_type}' can only be performed by the Buyer or Operator."
        )


class IsOperatorOrAdmin(permissions.BasePermission):
    """DRF permission class restricting view access to Platform Operators and Product Admins."""

    def has_permission(self, request, view):
        return is_operator_or_admin(request.user)


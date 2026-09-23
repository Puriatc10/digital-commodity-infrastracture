from typing import Any

from rest_framework import permissions

from execution.exceptions import ExecutionPermissionDeniedError
from identity.models import SystemRoleAssignment


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


class IsOperatorOrAdmin(permissions.BasePermission):
    """DRF permission class restricting view access to Platform Operators and Product Admins."""

    def has_permission(self, request, view):
        return is_operator_or_admin(request.user)

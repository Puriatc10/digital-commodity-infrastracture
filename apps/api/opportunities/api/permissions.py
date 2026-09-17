from rest_framework import permissions

from identity.models import SystemRoleAssignment


def is_operator_or_product_admin(user) -> bool:
    """
    Check if the user has an active Operator or Admin system role assignment.

    Django is_staff and is_superuser alone grant NO privileges.
    Membership in Buyer/Supplier/Broker organizations grants NO privileges.
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


class IsOperatorOrProductAdmin(permissions.BasePermission):
    """
    Strict Market Discovery authorization policy.

    Allows access ONLY to authenticated users with active Operator or Admin system roles.
    Rejects:
    - Anonymous users (401 handled by DRF authentication)
    - Regular users, Buyer, Supplier, Broker organization members (403)
    - Django staff-only or superuser-only users without explicit SystemRoleAssignment (403)
    """

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        return is_operator_or_product_admin(request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        return is_operator_or_product_admin(request.user)

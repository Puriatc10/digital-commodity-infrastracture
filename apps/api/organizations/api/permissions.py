from rest_framework import permissions
from identity.models import SystemRoleAssignment
from organizations.models import OrganizationMembership


def get_active_system_roles(user):
    """Return a set of active system roles for the user."""
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    return set(user.system_roles.values_list('role', flat=True))


def has_system_role(user, role):
    """Check if the user has a specific active system role."""
    return role in get_active_system_roles(user)


def get_active_membership(user, organization):
    """Return the active OrganizationMembership for the user in the organization, or None."""
    if not user or not user.is_authenticated or not user.is_active:
        return None
    if getattr(organization, "is_active", True) is False:
        return None
    return OrganizationMembership.objects.filter(
        user=user,
        organization=organization,
        is_active=True
    ).first()


def has_organization_role(user, organization, roles):
    """Check if the user has one of the specified roles in the organization."""
    if isinstance(roles, str):
        roles = [roles]
    membership = get_active_membership(user, organization)
    if not membership:
        return False
    return membership.role in roles


class IsOrganizationMemberOrAdmin(permissions.BasePermission):
    """
    Permission for Organization endpoints.
    - View: Members of the organization (any role) OR System Operator/Admin.
    - Update: Owner/Manager of the organization OR System Admin.
    """

    def has_permission(self, request, view):
        # We handle general access to the ViewSet.
        # get_queryset will handle filtering the list.
        # Object-level permissions will handle detail access.
        if not bool(request.user and request.user.is_authenticated and request.user.is_active):
            return False
        return True

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated or not request.user.is_active:
            return False

        system_roles = get_active_system_roles(request.user)
        is_operator_or_admin = bool(
            SystemRoleAssignment.SystemRole.OPERATOR in system_roles or
            SystemRoleAssignment.SystemRole.ADMIN in system_roles
        )

        membership = get_active_membership(request.user, obj)
        is_active_member = membership is not None

        if request.method in permissions.SAFE_METHODS:
            return is_active_member or is_operator_or_admin

        if request.method in ["PUT", "PATCH"]:
            is_admin = SystemRoleAssignment.SystemRole.ADMIN in system_roles
            is_manager_or_owner = False
            if is_active_member and membership.role in [
                OrganizationMembership.OrganizationRole.MANAGER,
                OrganizationMembership.OrganizationRole.OWNER,
            ]:
                is_manager_or_owner = True

            return is_admin or is_manager_or_owner

        return False

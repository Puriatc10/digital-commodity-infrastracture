from rest_framework import permissions
from organizations.models import OrganizationMembership

class CanViewVerification(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # obj is Organization
        if not obj.is_active:
             # System operator/admin can view inactive
             return request.user.system_roles.filter(role__in=['operator', 'admin']).exists()

        # Member/Viewer can view their own
        if obj.memberships.filter(user=request.user, is_active=True).exists():
             return True

        # System roles can view any
        return request.user.system_roles.filter(role__in=['operator', 'admin']).exists()

class CanSubmitVerification(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not obj.is_active:
             return False

        # Only Owner/Manager can submit
        return obj.memberships.filter(
            user=request.user,
            is_active=True,
            role__in=[OrganizationMembership.OrganizationRole.OWNER, OrganizationMembership.OrganizationRole.MANAGER]
        ).exists()

class CanPerformVerificationReview(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Review mutations cannot be performed on inactive organizations
        if not obj.is_active:
             return False

        # Only operator/admin system roles can review/approve/reject
        return request.user.system_roles.filter(role__in=['operator', 'admin']).exists()

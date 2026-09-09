from rest_framework import viewsets, mixins
from django.db.models import Q
from organizations.models import Organization
from organizations.api.serializers import OrganizationSerializer
from organizations.api.permissions import IsOrganizationMemberOrAdmin, get_active_system_roles
from identity.models import SystemRoleAssignment

class OrganizationViewSet(mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin,
                          mixins.ListModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [IsOrganizationMemberOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated or not user.is_active:
            return Organization.objects.none()

        system_roles = get_active_system_roles(user)
        is_operator_or_admin = bool(
            SystemRoleAssignment.SystemRole.OPERATOR in system_roles or
            SystemRoleAssignment.SystemRole.ADMIN in system_roles
        )

        if is_operator_or_admin:
            # Operators and Admins can see all organizations.
            # (Note: is_active org filtering is not strictly enforced here for them
            # if they need to see inactive ones, but the system role access grants system-wide view).
            return Organization.objects.all()

        # Regular users only see organizations where they have an active membership
        # and the organization itself is active (though we could allow them to see inactive orgs if they are members,
        # but requirements suggest active memberships are required).
        return Organization.objects.filter(
            is_active=True,
            memberships__user=user,
            memberships__is_active=True
        ).distinct()

    def update(self, request, *args, **kwargs):
        # We only support PATCH as per requirements. But DRF GenericViewSet maps PUT to update by default.
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)

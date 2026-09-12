from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from django.db.models import Q
from .serializers import DirectoryOrganizationSerializer, OrganizationProfileSerializer, CommodityAssociationSerializer
from rest_framework import permissions
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from organizations.api.permissions import CanManageOrganizationCommodities
from commodities.models import CommodityDefinition
from organizations.models import OrganizationCommodity
from rest_framework import viewsets, mixins
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

    @extend_schema(request=CommodityAssociationSerializer, responses={201: None})
    @action(detail=True, methods=['post'], permission_classes=[CanManageOrganizationCommodities])
    def add_commodity(self, request, pk=None):
        organization = self.get_object()
        commodity_code = request.data.get("commodity_code")
        if not commodity_code:
            return Response({"detail": "commodity_code is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            commodity = CommodityDefinition.objects.get(code=commodity_code)
        except CommodityDefinition.DoesNotExist:
            return Response({"detail": "Commodity not found."}, status=status.HTTP_404_NOT_FOUND)

        OrganizationCommodity.objects.get_or_create(organization=organization, commodity=commodity)
        return Response({"detail": "Commodity added successfully."}, status=status.HTTP_201_CREATED)

    @extend_schema(request=CommodityAssociationSerializer, responses={204: None})
    @action(detail=True, methods=['delete'], permission_classes=[CanManageOrganizationCommodities])
    def remove_commodity(self, request, pk=None):
        organization = self.get_object()
        commodity_code = request.data.get("commodity_code")
        if not commodity_code:
            return Response({"detail": "commodity_code is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            commodity = CommodityDefinition.objects.get(code=commodity_code)
        except CommodityDefinition.DoesNotExist:
            return Response({"detail": "Commodity not found."}, status=status.HTTP_404_NOT_FOUND)

        OrganizationCommodity.objects.filter(organization=organization, commodity=commodity).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(name="search", type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name="capability", type=OpenApiTypes.STR, many=True, explode=True, required=False),
            OpenApiParameter(name="country", type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name="commodity", type=OpenApiTypes.STR, many=True, explode=True, required=False),
            OpenApiParameter(name="verification", type=OpenApiTypes.STR, many=True, explode=True, required=False),
        ]
    )
)
class DirectoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = DirectoryOrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated or not user.is_active:
            return Organization.objects.none()

        qs = Organization.objects.select_related('verification').prefetch_related('capabilities', 'commodities__commodity').filter(is_active=True).distinct()

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)

        capabilities = self.request.query_params.getlist("capability")
        if capabilities:
            qs = qs.filter(capabilities__capability__in=capabilities)

        country = self.request.query_params.get("country")
        if country:
            qs = qs.filter(country=country)

        commodities = self.request.query_params.getlist("commodity")
        if commodities:
            qs = qs.filter(commodities__commodity__code__in=commodities)

        verifications = self.request.query_params.getlist("verification")
        if verifications:
            if "unverified" in verifications:
                qs = qs.filter(Q(verification__status__in=verifications) | Q(verification__isnull=True))
            else:
                qs = qs.filter(verification__status__in=verifications)

        return qs.order_by("name")


class ProfileViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OrganizationProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated or not user.is_active:
            return Organization.objects.none()

        # Profiles can only be viewed if the organization is active
        # All authenticated users can view profiles of active organizations
        return Organization.objects.filter(is_active=True).distinct()

from django.db import models
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from .serializers import (
    DirectoryOrganizationSerializer,
    OrganizationProfileSerializer,
    OrganizationSerializer,
    OrganizationCommodityActionSerializer
)
from rest_framework import permissions
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from organizations.api.permissions import CanManageOrganizationCommodities
from commodities.models import CommodityDefinition
from organizations.models import OrganizationCommodity
from rest_framework import viewsets, mixins
from organizations.models import Organization
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
            return Organization.objects.all()

        # Regular users only see organizations where they have an active membership
        # and the organization itself is active.
        return Organization.objects.filter(
            is_active=True,
            memberships__user=user,
            memberships__is_active=True
        ).distinct()

    @extend_schema(
        request=OrganizationCommodityActionSerializer,
        responses={
            201: OpenApiResponse(description="Commodity added successfully."),
            400: OpenApiResponse(description="Invalid request or commodity_code missing."),
            403: OpenApiResponse(description="Not authorized to manage commodities for this organization."),
            404: OpenApiResponse(description="Commodity not found."),
        }
    )
    @action(detail=True, methods=['post'], permission_classes=[CanManageOrganizationCommodities])
    def add_commodity(self, request, pk=None):
        organization = self.get_object()
        serializer = OrganizationCommodityActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        commodity_code = serializer.validated_data["commodity_code"]
        try:
            commodity = CommodityDefinition.objects.get(code=commodity_code)
        except CommodityDefinition.DoesNotExist:
            return Response({"detail": "Commodity not found."}, status=status.HTTP_404_NOT_FOUND)

        OrganizationCommodity.objects.get_or_create(organization=organization, commodity=commodity)
        return Response({"detail": "Commodity added successfully."}, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=OrganizationCommodityActionSerializer,
        responses={
            204: OpenApiResponse(description="Commodity removed successfully."),
            400: OpenApiResponse(description="Invalid request or commodity_code missing."),
            403: OpenApiResponse(description="Not authorized to manage commodities for this organization."),
            404: OpenApiResponse(description="Commodity not found."),
        }
    )
    @action(detail=True, methods=['delete'], permission_classes=[CanManageOrganizationCommodities])
    def remove_commodity(self, request, pk=None):
        organization = self.get_object()
        serializer = OrganizationCommodityActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        commodity_code = serializer.validated_data["commodity_code"]
        try:
            commodity = CommodityDefinition.objects.get(code=commodity_code)
        except CommodityDefinition.DoesNotExist:
            return Response({"detail": "Commodity not found."}, status=status.HTTP_404_NOT_FOUND)

        OrganizationCommodity.objects.filter(organization=organization, commodity=commodity).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DirectoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = DirectoryOrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated or not user.is_active:
            return Organization.objects.none()

        qs = (
            Organization.objects.filter(is_active=True)
            .select_related("verification")
            .prefetch_related("capabilities", "commodities__commodity")
            .distinct()
        )

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
                qs = qs.filter(
                    models.Q(verification__status__in=verifications) | models.Q(verification__isnull=True)
                )
            else:
                qs = qs.filter(verification__status__in=verifications)

        return qs.order_by("name", "id")

    @extend_schema(
        parameters=[
            OpenApiParameter(name="search", type=OpenApiTypes.STR, required=False, description="Search by organization name"),
            OpenApiParameter(name="capability", type=OpenApiTypes.STR, many=True, required=False, description="Filter by business capability (buyer, supplier, broker)"),
            OpenApiParameter(name="country", type=OpenApiTypes.STR, required=False, description="Filter by country ISO code"),
            OpenApiParameter(name="commodity", type=OpenApiTypes.STR, many=True, required=False, description="Filter by commodity code"),
            OpenApiParameter(name="verification", type=OpenApiTypes.STR, many=True, required=False, description="Filter by verification status"),
        ],
        responses={200: DirectoryOrganizationSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class ProfileViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OrganizationProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated or not user.is_active:
            return Organization.objects.none()

        # Profiles can only be viewed if the organization is active
        # All authenticated users can view profiles of active organizations
        return (
            Organization.objects.filter(is_active=True)
            .select_related("verification")
            .prefetch_related("capabilities", "commodities__commodity")
            .distinct()
        )

    @extend_schema(
        responses={
            200: OrganizationProfileSerializer,
            404: OpenApiResponse(description="Organization profile not found or inactive")
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


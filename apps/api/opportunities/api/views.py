from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, viewsets
from rest_framework.pagination import PageNumberPagination

from opportunities.api.permissions import IsOperatorOrProductAdmin
from opportunities.api.serializers import ExternalCounterpartySerializer
from opportunities.models import ExternalCounterparty


class ExternalCounterpartyPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        summary="List external counterparties",
        description=(
            "List and search external counterparties recorded by Operators. "
            "Supports text search across company name, contact name, email, phone, and geography."
        ),
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search across company name, contact person, email, phone, or geography.",
            ),
            OpenApiParameter(
                name="company_name",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by company name substring.",
            ),
            OpenApiParameter(
                name="geography",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by geography or location substring.",
            ),
        ],
        responses={
            200: ExternalCounterpartySerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
        },
    ),
    create=extend_schema(
        summary="Record external counterparty",
        description=(
            "Create a new external counterparty record without creating a platform User, "
            "Organization, OrganizationMembership, or OrganizationCapability."
        ),
        request=ExternalCounterpartySerializer,
        responses={
            201: ExternalCounterpartySerializer,
            400: OpenApiResponse(description="Validation error (e.g. blank company name, invalid email)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
        },
    ),
    retrieve=extend_schema(
        summary="Retrieve external counterparty details",
        description="Retrieve the details of a single external counterparty by UUID.",
        responses={
            200: ExternalCounterpartySerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="External counterparty not found"),
        },
    ),
    update=extend_schema(
        summary="Update external counterparty (full)",
        description="Update all editable fields of an existing external counterparty.",
        request=ExternalCounterpartySerializer,
        responses={
            200: ExternalCounterpartySerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="External counterparty not found"),
        },
    ),
    partial_update=extend_schema(
        summary="Update external counterparty (partial)",
        description="Partially update editable fields of an existing external counterparty.",
        request=ExternalCounterpartySerializer,
        responses={
            200: ExternalCounterpartySerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="External counterparty not found"),
        },
    ),
)
class ExternalCounterpartyViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Operator workspace API for managing off-platform External Counterparties.

    Deletion is intentionally NOT implemented or exposed in order to preserve
    future Opportunity historical provenance.
    """

    queryset = ExternalCounterparty.objects.all().select_related("created_by")
    serializer_class = ExternalCounterpartySerializer
    permission_classes = [IsOperatorOrProductAdmin]
    pagination_class = ExternalCounterpartyPagination
    lookup_field = "id"

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(company_name__icontains=search)
                | Q(contact_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(geography__icontains=search)
            )

        company_name = self.request.query_params.get("company_name", "").strip()
        if company_name:
            queryset = queryset.filter(company_name__icontains=company_name)

        geography = self.request.query_params.get("geography", "").strip()
        if geography:
            queryset = queryset.filter(geography__icontains=geography)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user if getattr(self.request, "user", None) and self.request.user.is_authenticated else None
        serializer.save(created_by=user)

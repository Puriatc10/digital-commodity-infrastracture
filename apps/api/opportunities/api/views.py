from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from opportunities.api.permissions import IsOperatorOrProductAdmin
from opportunities.api.serializers import (
    ExternalCounterpartySerializer,
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityUpdateSerializer,
)
from opportunities.models import ExternalCounterparty, Opportunity



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


class OpportunityPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        summary="List opportunities",
        description=(
            "List and filter trade opportunities (Supply and Demand) captured by Operators. "
            "Supports filtering by direction, status, and commodity."
        ),
        parameters=[
            OpenApiParameter(
                name="direction",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by direction (Supply or Demand).",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by opportunity status (e.g. Captured).",
            ),
            OpenApiParameter(
                name="commodity",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by commodity code (e.g. bitumen).",
            ),
        ],
        responses={
            200: OpportunityDetailSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
        },
    ),
    create=extend_schema(
        summary="Capture opportunity",
        description=(
            "Capture a new trade lead (Supply or Demand) linked to either an internal registered "
            "Organization or an off-platform ExternalCounterparty."
        ),
        request=OpportunityCreateSerializer,
        responses={
            201: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error (e.g. counterparty exclusivity violation, invalid direction)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
        },
    ),
    retrieve=extend_schema(
        summary="Retrieve opportunity details",
        description="Retrieve full details and safe counterparty/commodity projection for a single opportunity by UUID.",
        responses={
            200: OpportunityDetailSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    ),
    update=extend_schema(
        summary="Update opportunity (full)",
        description="Update editable commercial and counterparty fields of an existing opportunity.",
        request=OpportunityUpdateSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    ),
    partial_update=extend_schema(
        summary="Update opportunity (partial)",
        description="Partially update editable commercial and counterparty fields of an existing opportunity.",
        request=OpportunityUpdateSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    ),
)
class OpportunityViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Operator workspace API for managing Market Discovery Opportunities.

    Deletion is intentionally NOT exposed (returns 405 Method Not Allowed)
    to preserve historical provenance.
    """

    queryset = (
        Opportunity.objects.all()
        .select_related("organization", "external_counterparty", "commodity", "created_by")
    )
    permission_classes = [IsOperatorOrProductAdmin]
    pagination_class = OpportunityPagination
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "create":
            return OpportunityCreateSerializer
        if self.action in ["update", "partial_update"]:
            return OpportunityUpdateSerializer
        return OpportunityDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        direction = self.request.query_params.get("direction", "").strip()
        if direction:
            queryset = queryset.filter(direction__iexact=direction)

        status_param = self.request.query_params.get("status", "").strip()
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        commodity = self.request.query_params.get("commodity", "").strip()
        if commodity:
            queryset = queryset.filter(commodity__code=commodity)

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None

        opportunity = Opportunity.objects.create(
            direction=validated["direction"],
            organization_id=validated.get("organization_id"),
            external_counterparty_id=validated.get("external_counterparty_id"),
            commodity_id=validated.get("commodity_id"),
            quantity=validated.get("quantity"),
            unit=validated.get("unit", "MT"),
            indicative_price=validated.get("indicative_price"),
            currency=validated.get("currency", "USD"),
            delivery_window_start=validated.get("delivery_window_start"),
            delivery_window_end=validated.get("delivery_window_end"),
            payment_terms=validated.get("payment_terms", ""),
            geography=validated.get("geography", ""),
            notes=validated.get("notes", ""),
            created_by=user,
        )

        response_serializer = OpportunityDetailSerializer(opportunity)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        for field, value in validated.items():
            setattr(instance, field, value)

        instance.save()
        response_serializer = OpportunityDetailSerializer(instance)
        return Response(response_serializer.data)

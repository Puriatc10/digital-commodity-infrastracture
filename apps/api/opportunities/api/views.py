import uuid

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from opportunities.api.permissions import IsOperatorOrProductAdmin
from opportunities.api.serializers import (
    ExternalCounterpartySerializer,
    OpportunityContactActionSerializer,
    OpportunityContactAttemptCreateSerializer,
    OpportunityContactAttemptDetailSerializer,
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityExpireActionSerializer,
    OpportunityHoldActionSerializer,
    OpportunityLostActionSerializer,
    OpportunityMatchActionSerializer,
    OpportunityQualificationErrorResponseSerializer,
    OpportunityQualifyActionSerializer,
    OpportunityRejectActionSerializer,
    OpportunityResumeActionSerializer,
    OpportunityTaskCreateSerializer,
    OpportunityTaskDetailSerializer,
    OpportunityTaskUpdateSerializer,
    OpportunityUpdateSerializer,
)
from opportunities.exceptions import (
    ContactAttemptNotFoundError,
    InvalidTransitionError,
    InvalidVersionError,
    OpportunityNotFoundError,
    OpportunityPermissionDeniedError,
    OpportunityQualificationError,
    OpportunityTaskNotFoundError,
    ReservedTransitionError,
    StaleVersionError,
)
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunitySource,
    OpportunityTaskStatus,
)
from opportunities.services import (
    cancel_opportunity_task,
    complete_opportunity_task,
    create_opportunity,
    create_opportunity_task,
    get_contact_attempt,
    get_opportunity_task,
    list_contact_attempts,
    list_opportunity_tasks,
    record_contact_attempt,
    update_opportunity,
    update_opportunity_task,
)
from opportunities.services_lifecycle import OpportunityLifecycleService




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
            OpenApiParameter(
                name="identifier",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by exact human-readable identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="source",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by opportunity origin source (e.g. broker_referral, operator_sourcing).",
            ),
            OpenApiParameter(
                name="broker",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by attributed broker organization UUID.",
            ),
            OpenApiParameter(
                name="assigned_to_me",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter opportunities that have at least one open follow-up task assigned to the current operator.",
            ),
            OpenApiParameter(
                name="follow_up_required",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter opportunities that have at least one open follow-up task that is due or overdue.",
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
        .select_related("organization", "external_counterparty", "commodity", "broker", "created_by")
    )
    permission_classes = [IsOperatorOrProductAdmin]
    pagination_class = OpportunityPagination
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "create":
            return OpportunityCreateSerializer
        if self.action in ["update", "partial_update"]:
            return OpportunityUpdateSerializer
        if self.action == "contact":
            return OpportunityContactActionSerializer
        if self.action == "qualify":
            return OpportunityQualifyActionSerializer
        if self.action == "match":
            return OpportunityMatchActionSerializer
        if self.action == "hold":
            return OpportunityHoldActionSerializer
        if self.action == "resume":
            return OpportunityResumeActionSerializer
        if self.action == "reject":
            return OpportunityRejectActionSerializer
        if self.action == "lost":
            return OpportunityLostActionSerializer
        if self.action == "expire":
            return OpportunityExpireActionSerializer
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

        identifier = self.request.query_params.get("identifier", "").strip()
        if identifier:
            queryset = queryset.filter(identifier=identifier)

        source = self.request.query_params.get("source", "").strip()
        if source:
            queryset = queryset.filter(source__iexact=source)

        broker = self.request.query_params.get("broker", "").strip()
        if broker:
            queryset = queryset.filter(broker_id=broker)

        assigned_to_me = self.request.query_params.get("assigned_to_me", "").strip().lower()
        if assigned_to_me in ("true", "1") and getattr(self.request, "user", None) and self.request.user.is_authenticated:
            queryset = queryset.filter(
                tasks__assigned_to=self.request.user,
                tasks__status=OpportunityTaskStatus.OPEN,
            ).distinct()

        follow_up_required = self.request.query_params.get("follow_up_required", "").strip().lower()
        if follow_up_required in ("true", "1"):
            queryset = queryset.filter(
                tasks__status=OpportunityTaskStatus.OPEN,
                tasks__due_at__lte=timezone.now(),
            ).distinct()

        return queryset


    def get_object(self):
        lookup_val = self.kwargs.get(self.lookup_field)
        queryset = self.filter_queryset(self.get_queryset())
        try:
            uuid.UUID(str(lookup_val))
            obj = queryset.filter(id=lookup_val).first()
        except (ValueError, AttributeError):
            obj = queryset.filter(identifier=lookup_val).first()

        if obj is None:
            raise Http404("No Opportunity matches the given query.")

        self.check_object_permissions(self.request, obj)
        return obj

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None

        opportunity = create_opportunity(
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
            source=validated.get("source", OpportunitySource.OPERATOR_SOURCING),
            broker_id=validated.get("broker_id"),
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

        try:
            instance = update_opportunity(instance, data=validated)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, InvalidTransitionError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = OpportunityDetailSerializer(instance)
        return Response(response_serializer.data)

    def _execute_lifecycle_action(self, request, serializer_class, action_func, **extra_kwargs):
        instance = self.get_object()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data["expected_version"]

        kwargs = {**extra_kwargs}
        if "reason" in serializer.validated_data:
            kwargs["reason"] = serializer.validated_data["reason"]

        try:
            opp = action_func(
                instance.id,
                expected_version=expected_version,
                actor=request.user,
                **kwargs,
            )
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except OpportunityQualificationError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "qualifiable": False,
                    "missing_requirements": [i.to_dict() for i in exc.missing_requirements],
                    "invalid_requirements": [i.to_dict() for i in exc.invalid_requirements],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (InvalidVersionError, InvalidTransitionError, ReservedTransitionError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except OpportunityNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except OpportunityPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        return Response(OpportunityDetailSerializer(opp).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Mark opportunity as contacted",
        description="Transition an Opportunity from Captured to Contacted. Requires expected_version for optimistic concurrency control.",
        request=OpportunityContactActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or invalid transition"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="contact")
    def contact(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityContactActionSerializer,
            OpportunityLifecycleService.mark_contacted,
        )

    @extend_schema(
        summary="Qualify opportunity",
        description=(
            "Transition an Opportunity to Qualified. Requires expected_version for optimistic concurrency control "
            "and evaluates persisted aggregate data against the authoritative qualification contract."
        ),
        request=OpportunityQualifyActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpportunityQualificationErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="qualify")
    def qualify(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityQualifyActionSerializer,
            OpportunityLifecycleService.qualify,
        )

    @extend_schema(
        summary="Move opportunity to matching",
        description="Transition a Qualified Opportunity into Matching. Requires expected_version for optimistic concurrency control.",
        request=OpportunityMatchActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or invalid transition"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="match")
    def match(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityMatchActionSerializer,
            OpportunityLifecycleService.start_matching,
        )

    @extend_schema(
        summary="Put opportunity on hold",
        description="Transition an active Opportunity to On Hold. Requires expected_version and mandatory non-empty reason.",
        request=OpportunityHoldActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or missing reason"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityHoldActionSerializer,
            OpportunityLifecycleService.put_on_hold,
        )

    @extend_schema(
        summary="Resume opportunity from hold",
        description="Resume an Opportunity from On Hold back to its pre-hold status. Requires expected_version.",
        request=OpportunityResumeActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or invalid transition"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityResumeActionSerializer,
            OpportunityLifecycleService.resume,
        )

    @extend_schema(
        summary="Reject opportunity",
        description="Transition an Opportunity to Rejected (terminal). Requires expected_version and mandatory non-empty reason.",
        request=OpportunityRejectActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or missing reason"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityRejectActionSerializer,
            OpportunityLifecycleService.reject,
        )

    @extend_schema(
        summary="Mark opportunity as lost",
        description="Transition an Opportunity to Lost (terminal). Requires expected_version and mandatory non-empty reason.",
        request=OpportunityLostActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or missing reason"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="lost")
    def lost(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityLostActionSerializer,
            OpportunityLifecycleService.mark_lost,
        )

    @extend_schema(
        summary="Expire opportunity",
        description="Transition an Opportunity to Expired (terminal). Requires expected_version.",
        request=OpportunityExpireActionSerializer,
        responses={
            200: OpportunityDetailSerializer,
            400: OpenApiResponse(description="Validation error or invalid transition"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
            409: OpenApiResponse(description="Conflict — stale expected_version"),
        },
    )
    @action(detail=True, methods=["post"], url_path="expire")
    def expire(self, request, id=None):
        return self._execute_lifecycle_action(
            request,
            OpportunityExpireActionSerializer,
            OpportunityLifecycleService.expire,
        )


def _resolve_opportunity_for_attempts(opportunity_id: str) -> Opportunity:
    try:
        val = uuid.UUID(str(opportunity_id))
        opp = Opportunity.objects.filter(id=val).first()
    except (ValueError, AttributeError):
        opp = Opportunity.objects.filter(identifier=str(opportunity_id).strip()).first()

    if opp is None:
        raise Http404(f"No Opportunity found matching '{opportunity_id}'.")
    return opp


class OpportunityContactAttemptListCreateView(APIView):
    """
    Chronological operational contact attempt history for an Opportunity.
    Append-only: creates and lists contact attempts (Call, Message, Email, Meeting, Note).
    Strictly restricted to Operator and Product Admin roles.
    """

    permission_classes = [IsOperatorOrProductAdmin]

    @extend_schema(
        summary="List opportunity contact attempts",
        description=(
            "Retrieve chronological contact attempts for a specific opportunity in deterministic order "
            "(most recent interaction first). Strictly restricted to Operator and Product Admin roles."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
        ],
        responses={
            200: OpportunityContactAttemptDetailSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    )
    def get(self, request, opportunity_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        attempts = list_contact_attempts(opp.id)
        serializer = OpportunityContactAttemptDetailSerializer(attempts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Record contact attempt",
        description=(
            "Record a new interaction (Call, Message, Email, Meeting, Note) for an opportunity. "
            "Append-only: recorder is derived from authenticated user. Does not alter opportunity "
            "lifecycle status or version."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
        ],
        request=OpportunityContactAttemptCreateSerializer,
        responses={
            201: OpportunityContactAttemptDetailSerializer,
            400: OpenApiResponse(description="Validation error (e.g. invalid type, future timestamp)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    )
    def post(self, request, opportunity_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        serializer = OpportunityContactAttemptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        try:
            attempt = record_contact_attempt(
                opp.id,
                type=validated["type"],
                occurred_at=validated.get("occurred_at"),
                notes=validated.get("notes", ""),
                actor=request.user,
            )
        except ValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = OpportunityContactAttemptDetailSerializer(attempt)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class OpportunityContactAttemptDetailView(APIView):
    """
    Retrieve single contact attempt scoped to parent Opportunity.
    Append-only: PUT, PATCH, DELETE are not allowed.
    """

    permission_classes = [IsOperatorOrProductAdmin]

    @extend_schema(
        summary="Retrieve contact attempt detail",
        description=(
            "Retrieve a single contact attempt by UUID scoped to the specified opportunity. "
            "Strictly restricted to Operator and Product Admin roles."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="attempt_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Contact attempt UUID.",
            ),
        ],
        responses={
            200: OpportunityContactAttemptDetailSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Contact attempt or Opportunity not found"),
        },
    )
    def get(self, request, opportunity_id, attempt_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        try:
            attempt = get_contact_attempt(opp.id, attempt_id)
        except ContactAttemptNotFoundError as exc:
            raise Http404(str(exc))

        serializer = OpportunityContactAttemptDetailSerializer(attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)


# -------------------------------------------------------------------------
# Opportunity Task Views (T0607)
# -------------------------------------------------------------------------

class OpportunityTaskListCreateView(APIView):
    """
    List and create operational follow-up tasks for an Opportunity (Spec §22, Roadmap T0607).
    Strictly restricted to Operator and Product Admin roles.
    """

    permission_classes = [IsOperatorOrProductAdmin]
    serializer_class = OpportunityTaskDetailSerializer

    @extend_schema(
        summary="List opportunity follow-up tasks",
        description=(
            "Retrieve follow-up tasks for an opportunity in deterministic order (due_at ASC, created_at ASC, id ASC). "
            "Supports filtering by status, assigned_to, and overdue. Strictly restricted to Operator and Product Admin roles."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by task status: OPEN, COMPLETED, CANCELLED.",
            ),
            OpenApiParameter(
                name="assigned_to",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by assigned user ID (or 'me' for authenticated user).",
            ),
            OpenApiParameter(
                name="overdue",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter overdue open tasks (true/false).",
            ),
        ],
        responses={
            200: OpportunityTaskDetailSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    )
    def get(self, request, opportunity_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        status_param = request.query_params.get("status")
        assigned_to_param = request.query_params.get("assigned_to")
        overdue_param = request.query_params.get("overdue")

        assigned_to_id = None
        if assigned_to_param:
            if assigned_to_param.strip().lower() == "me":
                assigned_to_id = request.user.id if request.user and request.user.is_authenticated else None
            else:
                try:
                    assigned_to_id = int(assigned_to_param.strip())
                except ValueError:
                    assigned_to_id = None

        overdue_bool = None
        if overdue_param is not None:
            cleaned = overdue_param.strip().lower()
            if cleaned in ("true", "1"):
                overdue_bool = True
            elif cleaned in ("false", "0"):
                overdue_bool = False

        tasks = list_opportunity_tasks(
            opp.id,
            status=status_param,
            assigned_to_id=assigned_to_id,
            overdue=overdue_bool,
        )
        serializer = OpportunityTaskDetailSerializer(tasks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Create opportunity follow-up task",
        description=(
            "Create a new operational follow-up task scoped to the Opportunity. "
            "Creator is derived server-side from the authenticated user. "
            "If assigned_to is provided, user must be an active Operator or Admin."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
        ],
        request=OpportunityTaskCreateSerializer,
        responses={
            201: OpportunityTaskDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Opportunity not found"),
        },
    )
    def post(self, request, opportunity_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        serializer = OpportunityTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        try:
            task = create_opportunity_task(
                opp.id,
                title=validated["title"],
                due_at=validated["due_at"],
                description=validated.get("description", ""),
                assigned_to_id=validated.get("assigned_to"),
                actor=request.user,
            )
        except ValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = OpportunityTaskDetailSerializer(task)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class OpportunityTaskDetailView(APIView):
    """
    Retrieve and update an Opportunity follow-up task scoped strictly to its parent Opportunity.
    Strictly restricted to Operator and Product Admin roles.
    """

    permission_classes = [IsOperatorOrProductAdmin]
    serializer_class = OpportunityTaskDetailSerializer

    @extend_schema(
        summary="Retrieve opportunity follow-up task detail",
        description=(
            "Retrieve a single follow-up task by UUID scoped to the parent Opportunity. "
            "Strictly restricted to Operator and Product Admin roles."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="task_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Task UUID.",
            ),
        ],
        responses={
            200: OpportunityTaskDetailSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Task or Opportunity not found"),
        },
    )
    def get(self, request, opportunity_id, task_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        try:
            task = get_opportunity_task(opp.id, task_id)
        except OpportunityTaskNotFoundError as exc:
            raise Http404(str(exc))

        serializer = OpportunityTaskDetailSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update opportunity follow-up task",
        description=(
            "Update mutable attributes (title, description, due_at, assigned_to) of an OPEN follow-up task. "
            "Cannot modify status, completed_at, created_by, or parent Opportunity. "
            "Completed or cancelled tasks cannot be updated."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="task_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Task UUID.",
            ),
        ],
        request=OpportunityTaskUpdateSerializer,
        responses={
            200: OpportunityTaskDetailSerializer,
            400: OpenApiResponse(description="Validation error (e.g. ineligible assignee, task not OPEN)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Task or Opportunity not found"),
        },
    )
    def patch(self, request, opportunity_id, task_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        serializer = OpportunityTaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        kwargs = {}
        if "title" in validated:
            kwargs["title"] = validated["title"]
        if "description" in validated:
            kwargs["description"] = validated["description"]
        if "due_at" in validated:
            kwargs["due_at"] = validated["due_at"]
        if "assigned_to" in validated:
            kwargs["assigned_to_id"] = validated["assigned_to"]

        try:
            task = update_opportunity_task(
                opp.id,
                task_id,
                actor=request.user,
                **kwargs,
            )
        except OpportunityTaskNotFoundError as exc:
            raise Http404(str(exc))
        except ValidationError as exc:
            return Response(
                exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = OpportunityTaskDetailSerializer(task)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update opportunity follow-up task (full)",
        description=(
            "Update mutable attributes (title, description, due_at, assigned_to) of an OPEN follow-up task. "
            "Cannot modify status, completed_at, created_by, or parent Opportunity. "
            "Completed or cancelled tasks cannot be updated."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="task_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Task UUID.",
            ),
        ],
        request=OpportunityTaskUpdateSerializer,
        responses={
            200: OpportunityTaskDetailSerializer,
            400: OpenApiResponse(description="Validation error (e.g. ineligible assignee, task not OPEN)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Task or Opportunity not found"),
        },
    )
    def put(self, request, opportunity_id, task_id):
        return self.patch(request, opportunity_id, task_id)


class OpportunityTaskCompleteView(APIView):
    """
    Explicit action endpoint to complete an Opportunity follow-up task.
    Transitions OPEN -> COMPLETED and records server-side completed_at timestamp.
    Strictly restricted to Operator and Product Admin roles.
    """

    permission_classes = [IsOperatorOrProductAdmin]
    serializer_class = OpportunityTaskDetailSerializer


    @extend_schema(
        summary="Complete opportunity follow-up task",
        description=(
            "Explicit transition action to mark an OPEN follow-up task as COMPLETED. "
            "Sets completed_at server-side. Fails predictably if already completed or cancelled. "
            "Concurrency-safe via row-level locking."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="task_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Task UUID.",
            ),
        ],
        request=None,
        responses={
            200: OpportunityTaskDetailSerializer,
            400: OpenApiResponse(description="Invalid transition (e.g. task is already completed or cancelled)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Task or Opportunity not found"),
        },
    )
    def post(self, request, opportunity_id, task_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        try:
            task = complete_opportunity_task(opp.id, task_id, actor=request.user)
        except OpportunityTaskNotFoundError as exc:
            raise Http404(str(exc))
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = OpportunityTaskDetailSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OpportunityTaskCancelView(APIView):
    """
    Explicit action endpoint to cancel an Opportunity follow-up task.
    Transitions OPEN -> CANCELLED. Does not delete the task.
    Strictly restricted to Operator and Product Admin roles.
    """

    permission_classes = [IsOperatorOrProductAdmin]
    serializer_class = OpportunityTaskDetailSerializer


    @extend_schema(
        summary="Cancel opportunity follow-up task",
        description=(
            "Explicit transition action to mark an OPEN follow-up task as CANCELLED. "
            "Does not delete the task. Fails predictably if already completed or cancelled. "
            "Concurrency-safe via row-level locking."
        ),
        parameters=[
            OpenApiParameter(
                name="opportunity_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Opportunity UUID or canonical identifier (e.g. OPP-2026-000124).",
            ),
            OpenApiParameter(
                name="task_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="Task UUID.",
            ),
        ],
        request=None,
        responses={
            200: OpportunityTaskDetailSerializer,
            400: OpenApiResponse(description="Invalid transition (e.g. task is already completed or cancelled)"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden — Operator or Admin role required"),
            404: OpenApiResponse(description="Task or Opportunity not found"),
        },
    )
    def post(self, request, opportunity_id, task_id):
        opp = _resolve_opportunity_for_attempts(opportunity_id)
        try:
            task = cancel_opportunity_task(opp.id, task_id, actor=request.user)
        except OpportunityTaskNotFoundError as exc:
            raise Http404(str(exc))
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = OpportunityTaskDetailSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)

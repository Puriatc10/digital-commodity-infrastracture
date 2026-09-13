import uuid

from django.core.exceptions import ValidationError
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from trade_hub.api.serializers_rfq import (
    RFQActivityItemSerializer,
    RFQBuilderResponseSerializer,
    RFQCancelActionSerializer,
    RFQCloseActionSerializer,
    RFQCreateSerializer,
    RFQErrorResponseSerializer,
    RFQPublicResponseSerializer,
    RFQPublishActionSerializer,
    RFQUpdateSerializer,
)
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    PublicationValidationError,
    RFQNotFoundError,
    RFQPermissionDeniedError,
    SpecificationValidationError,
    StaleVersionError,
)
from trade_hub.services.rfq_service import (
    RFQService,
    create_draft_rfq,
    is_operator_or_admin,
    publish_draft_rfq,
    update_draft_rfq,
)
from trade_hub.services.visibility_service import (
    get_visible_rfq_for_request,
    get_visible_rfqs_for_request,
    resolve_authoritative_organization,
)


def _get_org_hint(request):
    return (
        getattr(request, "current_organization", None)
        or getattr(request, "organization", None)
        or (
            request.session.get("organization_id")
            if hasattr(request, "session")
            else None
        )
        or (
            request.headers.get("X-Organization-Id")
            if hasattr(request, "headers")
            else None
        )
        or (
            request.query_params.get("organization")
            if hasattr(request, "query_params")
            else None
        )
    )


class RFQPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class RFQListCreateView(APIView):
    """
    List RFQs visible to the caller or create a new RFQ Draft.
    Visibility-scoped: anonymous denied, external counterparties see only published RFQs,
    owners and operators see all lifecycle states.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List visible RFQs",
        description=(
            "Retrieve a paginated list of RFQs visible to the caller. "
            "Scoped strictly server-side according to the caller's active organization, "
            "capabilities, commodity associations, and explicit invitations."
        ),
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search query across origin, destination, organization name, notes, or commodity name/code.",
            ),
            OpenApiParameter(
                name="commodity",
                type=uuid.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by commodity definition UUID.",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by RFQ status.",
            ),
            OpenApiParameter(
                name="origin",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by origin country or port.",
            ),
            OpenApiParameter(
                name="destination",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by destination country or port.",
            ),
        ],
        responses={
            200: RFQPublicResponseSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def get(self, request):
        rfqs = (
            get_visible_rfqs_for_request(request)
            .select_related(
                "organization",
                "commodity",
                "schema_version",
                "organization__verification",
            )
            .prefetch_related(
                "organization__capabilities",
                "organization__commodities__commodity",
            )
        )

        search = request.query_params.get("search", "").strip()
        if search:
            rfqs = rfqs.filter(
                Q(origin__icontains=search)
                | Q(destination__icontains=search)
                | Q(organization__name__icontains=search)
                | Q(commodity__code__icontains=search)
                | Q(commodity__name_fa__icontains=search)
                | Q(commodity__name_en__icontains=search)
                | Q(notes__icontains=search)
            )

        commodity = request.query_params.get("commodity") or request.query_params.get(
            "commodity_id"
        )
        if commodity:
            try:
                commodity_uuid = uuid.UUID(str(commodity).strip())
                rfqs = rfqs.filter(commodity_id=commodity_uuid)
            except (ValueError, AttributeError):
                rfqs = rfqs.none()

        status_param = request.query_params.get("status", "").strip()
        if status_param:
            rfqs = rfqs.filter(status=status_param)

        origin = request.query_params.get("origin", "").strip()
        if origin:
            rfqs = rfqs.filter(origin__icontains=origin)

        destination = request.query_params.get("destination", "").strip()
        if destination:
            rfqs = rfqs.filter(destination__icontains=destination)

        rfqs = rfqs.distinct()

        paginator = RFQPagination()
        page = paginator.paginate_queryset(rfqs, request, view=self)

        current_org = resolve_authoritative_organization(
            request.user, _get_org_hint(request)
        )
        operator_flag = is_operator_or_admin(request.user)

        results = []
        for rfq in page:
            is_owner = bool(
                current_org and rfq.organization_id == current_org.pk
            ) or operator_flag
            if is_owner:
                results.append(RFQBuilderResponseSerializer(rfq).data)
            else:
                results.append(RFQPublicResponseSerializer(rfq).data)

        return paginator.get_paginated_response(results)

    @extend_schema(
        summary="Create RFQ draft",
        description=(
            "Create a new Draft RFQ. "
            "Buyer organization is bound server-side from the active organization context. "
            "Requires Owner or Manager role in a Buyer organization (or Platform Operator). "
            "Validates referenced commodity is active, referenced schema version is published, "
            "and dynamic specifications conform to the exact schema."
        ),
        request=RFQCreateSerializer,
        responses={
            201: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(
                description="Forbidden - lacks Buyer Owner/Manager role or Buyer capability"
            ),
        },
    )
    def post(self, request):
        serializer = RFQCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org_hint = _get_org_hint(request)
        try:
            rfq = create_draft_rfq(
                user=request.user,
                data=serializer.validated_data,
                organization_hint=org_hint,
            )
        except RFQPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except SpecificationValidationError as exc:
            return Response(
                {"detail": exc.message, "errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(exc, "params") and isinstance(exc.params, dict) and "errors" in exc.params:
                return Response(
                    {"detail": exc.message if hasattr(exc, "message") else str(exc), "errors": exc.params["errors"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": exc.message if hasattr(exc, "message") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out_serializer = RFQBuilderResponseSerializer(rfq)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class RFQDetailView(APIView):
    """
    Retrieve or update an RFQ.
    GET: Returns Builder projection for Owner/Operator or Public projection for permitted external viewers.
    PUT / PATCH: Updates Draft RFQ. Requires expected_version for optimistic concurrency control.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retrieve RFQ detail",
        description=(
            "Retrieve complete details of an RFQ. "
            "Returns the Builder projection (including internal notes and audit details) to the owning "
            "Buyer organization or Platform Operators. "
            "Returns the safe Public projection to external invited/network counterparties. "
            "Returns 404 if the RFQ does not exist or is hidden to the caller."
        ),
        responses={
            200: RFQBuilderResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="RFQ not found or not visible"),
        },
    )
    def get(self, request, rfq_id):
        try:
            rfq = get_visible_rfq_for_request(rfq_id, request)
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        current_org = resolve_authoritative_organization(
            request.user, _get_org_hint(request)
        )
        operator_flag = is_operator_or_admin(request.user)
        is_owner = bool(current_org and rfq.organization_id == current_org.pk) or operator_flag

        if is_owner:
            serializer = RFQBuilderResponseSerializer(rfq)
        else:
            serializer = RFQPublicResponseSerializer(rfq)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update draft RFQ",
        description=(
            "Update mutable fields of a Draft RFQ. "
            "Requires expected_version. Rejects stale versions with 409 Conflict. "
            "Rejects updates on Published, Closed, or Cancelled RFQs. "
            "Restricted to Buyer Owner/Manager or Platform Operator. "
            "Safely handles commodity/schema switching by re-validating specifications."
        ),
        request=RFQUpdateSerializer,
        responses={
            200: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks edit permissions"),
            404: OpenApiResponse(description="RFQ not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def put(self, request, rfq_id):
        return self._update(request, rfq_id)

    @extend_schema(
        summary="Partial update draft RFQ",
        description=(
            "Partially update mutable fields of a Draft RFQ. "
            "Requires expected_version for optimistic concurrency control."
        ),
        request=RFQUpdateSerializer,
        responses={
            200: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks edit permissions"),
            404: OpenApiResponse(description="RFQ not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def patch(self, request, rfq_id):
        return self._update(request, rfq_id)

    def _update(self, request, rfq_id):
        serializer = RFQUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data.pop("expected_version")
        org_hint = _get_org_hint(request)

        try:
            rfq = update_draft_rfq(
                rfq_or_id=rfq_id,
                data=serializer.validated_data,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except RFQPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except SpecificationValidationError as exc:
            return Response(
                {"detail": exc.message, "errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
            if hasattr(exc, "params") and isinstance(exc.params, dict) and "errors" in exc.params:
                return Response(
                    {"detail": exc.message if hasattr(exc, "message") else str(exc), "errors": exc.params["errors"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": exc.message if hasattr(exc, "message") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out_serializer = RFQBuilderResponseSerializer(rfq)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class RFQPublishActionView(APIView):
    """
    Publish a Draft RFQ.
    Requires expected_version. Delegates authoritatively to T0502 RFQLifecycleService.
    Validates dynamic specifications against stored exact schema version under row lock.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Publish RFQ",
        description=(
            "Transition a Draft RFQ to Published. "
            "Requires expected_version for optimistic concurrency control. "
            "Validates dynamic specifications against stored exact schema version under row lock. "
            "Freezes core technical and commercial terms upon successful publication."
        ),
        request=RFQPublishActionSerializer,
        responses={
            200: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks publish permissions"),
            404: OpenApiResponse(description="RFQ not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def post(self, request, rfq_id):
        serializer = RFQPublishActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        org_hint = _get_org_hint(request)

        try:
            rfq = publish_draft_rfq(
                rfq_or_id=rfq_id,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except RFQPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PublicationValidationError as exc:
            return Response(
                {"detail": exc.message, "errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out_serializer = RFQBuilderResponseSerializer(rfq)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class RFQCloseActionView(APIView):
    """
    Close a Published RFQ.
    Requires expected_version. Delegates authoritatively to RFQLifecycleService.close.
    Restricted to Buyer Owner/Manager or Platform Operator.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Close RFQ",
        description=(
            "Transition a Published RFQ to Closed. "
            "Requires expected_version for optimistic concurrency control. "
            "Restricted to Buyer Owner/Manager or Platform Operator. "
            "Rejects non-published RFQs with 400 Bad Request."
        ),
        request=RFQCloseActionSerializer,
        responses={
            200: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks close permissions"),
            404: OpenApiResponse(description="RFQ not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def post(self, request, rfq_id):
        serializer = RFQCloseActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        org_hint = _get_org_hint(request)

        try:
            rfq = RFQService.close(
                rfq_or_id=rfq_id,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except RFQPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = RFQBuilderResponseSerializer(rfq)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class RFQCancelActionView(APIView):
    """
    Cancel a Draft or Published RFQ.
    Requires expected_version. Cancelling a published RFQ requires a non-empty reason.
    Restricted to Buyer Owner/Manager or Platform Operator.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Cancel RFQ",
        description=(
            "Transition a Draft or Published RFQ to Cancelled. "
            "Requires expected_version for optimistic concurrency control. "
            "Cancelling a published RFQ requires a non-empty cancellation reason. "
            "Restricted to Buyer Owner/Manager or Platform Operator."
        ),
        request=RFQCancelActionSerializer,
        responses={
            200: RFQBuilderResponseSerializer,
            400: RFQErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks cancel permissions"),
            404: OpenApiResponse(description="RFQ not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def post(self, request, rfq_id):
        serializer = RFQCancelActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        reason = serializer.validated_data.get("reason", "")
        org_hint = _get_org_hint(request)

        try:
            rfq = RFQService.cancel(
                rfq_or_id=rfq_id,
                expected_version=expected_version,
                reason=reason,
                user=request.user,
                organization_hint=org_hint,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except RFQPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = RFQBuilderResponseSerializer(rfq)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class RFQActivityView(APIView):
    """
    Retrieve chronological audit activity facts for an RFQ.
    Reconstructed strictly from persisted facts on RFQ and RFQInvitation models.
    Actor-scoped: external participants never receive competitor details.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retrieve RFQ activity",
        description=(
            "Retrieve chronological audit facts for an RFQ. "
            "Buyer Owner/Manager or Platform Operator sees full activity history including all invitations. "
            "External participants see only public milestones and their own invitation events. "
            "Competitor events are strictly excluded."
        ),
        responses={
            200: RFQActivityItemSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="RFQ not found or not visible"),
        },
    )
    def get(self, request, rfq_id):
        org_hint = _get_org_hint(request)
        try:
            events = RFQService.get_activity(
                rfq_or_id=rfq_id,
                user=request.user,
                organization_hint=org_hint,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        serializer = RFQActivityItemSerializer(events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

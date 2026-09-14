import uuid

from django.core.exceptions import ValidationError
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from trade_hub.api.serializers_supply import (
    SupplyListingActivateActionSerializer,
    SupplyListingCloseActionSerializer,
    SupplyListingCreateSerializer,
    SupplyListingErrorResponseSerializer,
    SupplyListingPublicResponseSerializer,
    SupplyListingSupplierResponseSerializer,
    SupplyListingUpdateSerializer,
)
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    SpecificationValidationError,
    StaleVersionError,
    SupplyListingNotFoundError,
    SupplyListingPermissionDeniedError,
    SupplyListingValidationError,
)
from trade_hub.services.supply_service import (
    SupplyService,
    activate_draft_supply,
    create_draft_supply,
    is_operator_or_admin,
    update_draft_supply,
)
from trade_hub.services.visibility_service import (
    get_visible_supply_listing_for_request,
    get_visible_supply_listings_for_request,
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


class SupplyListingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class SupplyListingListCreateView(APIView):
    """
    List Supply Listings visible to the caller or create a new Supply Listing Draft.
    Visibility-scoped: anonymous denied, external counterparties see only Active listings,
    owners and operators see all lifecycle states.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List visible supply listings",
        description=(
            "Retrieve a paginated list of supply listings visible to the caller. "
            "Scoped strictly server-side according to the caller's active organization, "
            "capabilities, and commodity associations."
        ),
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search query across origin, destination, organization name, notes, quality notes, or commodity name/code.",
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
                description="Filter by supply listing status.",
            ),
            OpenApiParameter(
                name="origin",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by origin location or port.",
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
            200: SupplyListingPublicResponseSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def get(self, request):
        listings = (
            get_visible_supply_listings_for_request(request)
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
            listings = listings.filter(
                Q(origin__icontains=search)
                | Q(destination__icontains=search)
                | Q(organization__name__icontains=search)
                | Q(commodity__code__icontains=search)
                | Q(commodity__name_fa__icontains=search)
                | Q(commodity__name_en__icontains=search)
                | Q(notes__icontains=search)
                | Q(quality_notes__icontains=search)
            )

        commodity = request.query_params.get("commodity") or request.query_params.get(
            "commodity_id"
        )
        if commodity:
            try:
                commodity_uuid = uuid.UUID(str(commodity).strip())
                listings = listings.filter(commodity_id=commodity_uuid)
            except (ValueError, AttributeError):
                listings = listings.none()

        status_param = request.query_params.get("status", "").strip()
        if status_param:
            listings = listings.filter(status=status_param)

        origin = request.query_params.get("origin", "").strip()
        if origin:
            listings = listings.filter(origin__icontains=origin)

        destination = request.query_params.get("destination", "").strip()
        if destination:
            listings = listings.filter(destination__icontains=destination)

        listings = listings.distinct()

        paginator = SupplyListingPagination()
        page = paginator.paginate_queryset(listings, request, view=self)

        current_org = resolve_authoritative_organization(
            request.user, _get_org_hint(request)
        )
        operator_flag = is_operator_or_admin(request.user)

        results = []
        for listing in page:
            is_owner = bool(
                current_org and listing.organization_id == current_org.pk
            ) or operator_flag
            if is_owner:
                results.append(SupplyListingSupplierResponseSerializer(listing).data)
            else:
                results.append(SupplyListingPublicResponseSerializer(listing).data)

        return paginator.get_paginated_response(results)

    @extend_schema(
        summary="Create supply listing draft",
        description=(
            "Create a new Draft Supply Listing. "
            "Supplier organization is bound server-side from the active organization context. "
            "Requires Owner or Manager role in a Supplier organization (or Platform Operator). "
            "Validates referenced commodity is active, referenced schema version is published, "
            "and dynamic specifications conform to the exact schema."
        ),
        request=SupplyListingCreateSerializer,
        responses={
            201: SupplyListingSupplierResponseSerializer,
            400: SupplyListingErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(
                description="Forbidden - lacks Supplier Owner/Manager role or Supplier capability"
            ),
        },
    )
    def post(self, request):
        serializer = SupplyListingCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org_hint = _get_org_hint(request)
        try:
            listing = create_draft_supply(
                user=request.user,
                data=serializer.validated_data,
                organization_hint=org_hint,
            )
        except SupplyListingPermissionDeniedError as exc:
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

        out_serializer = SupplyListingSupplierResponseSerializer(listing)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class SupplyListingDetailView(APIView):
    """
    Retrieve or update a Supply Listing.
    GET: Returns Supplier projection for Owner/Operator or Public projection for permitted external viewers.
    PUT / PATCH: Updates Draft Supply Listing. Requires expected_version for optimistic concurrency control.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retrieve supply listing detail",
        description=(
            "Retrieve complete details of a Supply Listing. "
            "Returns the Supplier projection (including internal notes and audit details) to the owning "
            "Supplier organization or Platform Operators. "
            "Returns the safe Public projection to external counterparties. "
            "Returns 404 if the supply listing does not exist or is hidden to the caller."
        ),
        responses={
            200: SupplyListingSupplierResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Supply listing not found or not visible"),
        },
    )
    def get(self, request, listing_id):
        try:
            listing = get_visible_supply_listing_for_request(listing_id, request)
        except SupplyListingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        current_org = resolve_authoritative_organization(
            request.user, _get_org_hint(request)
        )
        operator_flag = is_operator_or_admin(request.user)
        is_owner = bool(current_org and listing.organization_id == current_org.pk) or operator_flag

        if is_owner:
            serializer = SupplyListingSupplierResponseSerializer(listing)
        else:
            serializer = SupplyListingPublicResponseSerializer(listing)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Update draft supply listing",
        description=(
            "Update mutable fields of a Draft Supply Listing. "
            "Requires expected_version. Rejects stale versions with 409 Conflict. "
            "Rejects updates on Active, Closed, or Expired listings. "
            "Restricted to Supplier Owner/Manager or Platform Operator. "
            "Safely handles commodity/schema switching by re-validating specifications."
        ),
        request=SupplyListingUpdateSerializer,
        responses={
            200: SupplyListingSupplierResponseSerializer,
            400: SupplyListingErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks edit permissions"),
            404: OpenApiResponse(description="Supply listing not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def put(self, request, listing_id):
        return self._update(request, listing_id)

    @extend_schema(
        summary="Partial update draft supply listing",
        description=(
            "Partially update mutable fields of a Draft Supply Listing. "
            "Requires expected_version for optimistic concurrency control."
        ),
        request=SupplyListingUpdateSerializer,
        responses={
            200: SupplyListingSupplierResponseSerializer,
            400: SupplyListingErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks edit permissions"),
            404: OpenApiResponse(description="Supply listing not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def patch(self, request, listing_id):
        return self._update(request, listing_id)

    def _update(self, request, listing_id):
        serializer = SupplyListingUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data.pop("expected_version")
        org_hint = _get_org_hint(request)

        try:
            listing = update_draft_supply(
                supply_or_id=listing_id,
                data=serializer.validated_data,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except SupplyListingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except SupplyListingPermissionDeniedError as exc:
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

        out_serializer = SupplyListingSupplierResponseSerializer(listing)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class SupplyListingActivateActionView(APIView):
    """
    Activate a Draft Supply Listing.
    Requires expected_version. Delegates authoritatively to SupplyLifecycleService.activate.
    Validates dynamic specifications against stored exact schema version under row lock.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Activate supply listing",
        description=(
            "Transition a Draft Supply Listing to Active. "
            "Requires expected_version for optimistic concurrency control. "
            "Validates dynamic specifications against stored exact schema version under row lock. "
            "Freezes core technical and commercial terms upon successful activation."
        ),
        request=SupplyListingActivateActionSerializer,
        responses={
            200: SupplyListingSupplierResponseSerializer,
            400: SupplyListingErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks activation permissions"),
            404: OpenApiResponse(description="Supply listing not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def post(self, request, listing_id):
        serializer = SupplyListingActivateActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        org_hint = _get_org_hint(request)

        try:
            listing = activate_draft_supply(
                supply_or_id=listing_id,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except SupplyListingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except SupplyListingPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except SupplyListingValidationError as exc:
            return Response(
                {"detail": exc.message, "errors": exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out_serializer = SupplyListingSupplierResponseSerializer(listing)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class SupplyListingCloseActionView(APIView):
    """
    Close a Draft or Active Supply Listing.
    Requires expected_version. Delegates authoritatively to SupplyLifecycleService.close.
    Restricted to Supplier Owner/Manager or Platform Operator.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Close supply listing",
        description=(
            "Transition a Draft or Active Supply Listing to Closed. "
            "Requires expected_version for optimistic concurrency control. "
            "Restricted to Supplier Owner/Manager or Platform Operator."
        ),
        request=SupplyListingCloseActionSerializer,
        responses={
            200: SupplyListingSupplierResponseSerializer,
            400: SupplyListingErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks close permissions"),
            404: OpenApiResponse(description="Supply listing not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version"),
        },
    )
    def post(self, request, listing_id):
        serializer = SupplyListingCloseActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        org_hint = _get_org_hint(request)

        try:
            listing = SupplyService.close(
                supply_or_id=listing_id,
                expected_version=expected_version,
                user=request.user,
                organization_hint=org_hint,
            )
        except SupplyListingNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except SupplyListingPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except InvalidVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = SupplyListingSupplierResponseSerializer(listing)
        return Response(out_serializer.data, status=status.HTTP_200_OK)

from typing import Any

from django.db import models
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from deals.api.serializers import (
    DealAttributionResolveRequestSerializer,
    DealAttributionSerializer,
    DealErrorResponseSerializer,
    DealMaterializeRequestSerializer,
    DealPartySnapshotSerializer,
    DealResponseSerializer,
    DealTermsSnapshotSerializer,
)
from deals.exceptions import (
    AttributionAlreadyResolvedError,
    AttributionNotFoundError,
    AwardNotFinalizedError,
    AwardNotFoundError,
    DealPermissionDeniedError,
    DealSourceIntegrityError,
    DealValidationError,
    StaleVersionError,
)
from deals.models import Deal
from deals.services.attribution_manual import manual_resolve_deal_attribution
from deals.services.materialization import (
    _is_operator_or_admin,
    materialize_deals_from_award,
)
from organizations.models import OrganizationMembership



def _check_deal_read_access(deal: Deal, user: Any) -> None:
    """
    Verify read authorization for a Deal aggregate and its snapshots.

    Authorized:
    - Platform OPERATOR or ADMIN with valid SystemRoleAssignment.
    - Active members of the Buyer Organization.
    - Active members of the Seller Organization (if internal).

    Denied:
    - Unrelated organizations / competitor participants.
    - Anonymous users.
    - External sellers (no platform user account).
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise DealPermissionDeniedError("Authentication required.")

    if _is_operator_or_admin(user):
        return

    allowed_org_ids = [deal.buyer_organization_id]
    if deal.seller_organization_id:
        allowed_org_ids.append(deal.seller_organization_id)

    is_party_member = OrganizationMembership.objects.filter(
        user=user,
        organization_id__in=allowed_org_ids,
        is_active=True,
        organization__is_active=True,
    ).exists()

    if not is_party_member:
        raise DealPermissionDeniedError("You do not have permission to access this deal.")


class DealMaterializeActionView(APIView):
    """
    Authoritative Deal materialization domain action (Epic 9 Contract §10, §60, T0901, T0902).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_materialize",
        tags=["Deals"],
        summary="Materialize Deals from Finalized Award",
        description=(
            "Authoritatively materializes one immutable Deal aggregate per AwardAllocation "
            "from a finalized Award, including immutable DealTermsSnapshot, DealCostSnapshot rows, "
            "and DealPartySnapshots. "
            "Enforces server-side derivation of Buyer and Seller identities from authoritative "
            "source records without accepting client commercial fields. "
            "Guarantees idempotency: repeated calls return existing Deals without creating duplicates "
            "or refreshing snapshots from mutated sources. "
            "Rejects unfinalized (DRAFT) Awards with a 400 Bad Request. "
            "Execution is serialized under PostgreSQL row-level locks."
        ),
        request=DealMaterializeRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=DealResponseSerializer(many=True),
                description="Idempotent result: existing Deals returned without duplication.",
            ),
            201: OpenApiResponse(
                response=DealResponseSerializer(many=True),
                description="Newly materialized Deals created from Award allocations.",
            ),
            400: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Validation error, unfinalized award, or source integrity mismatch.",
            ),
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: actor lacks authorization for this Award/RFQ.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Award not found.",
            ),
            409: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Conflict: stale expected_version.",
            ),
        },
    )
    def post(self, request, award_id):
        serializer = DealMaterializeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data.get("expected_version")

        try:
            deals, newly_created = materialize_deals_from_award(
                award_id=award_id,
                actor=request.user,
                expected_version=expected_version,
            )
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except AwardNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except StaleVersionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (AwardNotFinalizedError, DealSourceIntegrityError, DealValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        resp_serializer = DealResponseSerializer(deals, many=True, context={"request": request})
        resp_status = status.HTTP_201_CREATED if newly_created else status.HTTP_200_OK
        return Response(resp_serializer.data, status=resp_status)


class DealListView(APIView):
    """
    List Deals scoped server-side by authenticated actor (Contract §76, §97, T0901).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_list",
        tags=["Deals"],
        summary="List Deals",
        description=(
            "List Deal records visible to the authenticated actor. "
            "Server-side scoped: Buyer Organization members see their Buyer Deals; "
            "Seller Organization members see their Seller Deals; "
            "Platform Operators and Admins have global access. "
            "Unrelated organizations see an empty set."
        ),
        responses={
            200: OpenApiResponse(
                response=DealResponseSerializer(many=True),
                description="List of authorized Deals.",
            ),
            401: OpenApiResponse(description="Unauthenticated."),
        },
    )
    def get(self, request):
        if _is_operator_or_admin(request.user):
            qs = Deal.objects.all()
        else:
            user_org_ids = OrganizationMembership.objects.filter(
                user=request.user,
                is_active=True,
                organization__is_active=True,
            ).values_list("organization_id", flat=True)

            qs = Deal.objects.filter(
                models.Q(buyer_organization_id__in=user_org_ids)
                | models.Q(seller_organization_id__in=user_org_ids)
            )

        qs = (
            qs.select_related(
                "terms_snapshot",
                "terms_snapshot__commodity",
                "terms_snapshot__schema_version",
                "attribution",
            )
            .prefetch_related(
                "terms_snapshot__cost_snapshots",
                "party_snapshots",
                "broker_attributions",
                "broker_attributions__broker_organization",
                "broker_attributions__related_opportunity",
                "opportunity_attributions",
                "opportunity_attributions__opportunity",
            )
            .order_by("-created_at")
        )
        serializer = DealResponseSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class DealDetailView(APIView):
    """
    Retrieve minimal Deal aggregate by ID (Contract §76, §98, T0901, T0902).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_retrieve",
        tags=["Deals"],
        summary="Retrieve Deal by ID",
        description=(
            "Retrieves a Deal aggregate by UUID, including immutable terms and party snapshots. "
            "Access is strictly scoped to authorized members of the Buyer Organization, "
            "the Seller Organization, or platform Operators/Admins. "
            "Normal product APIs expose no mutation (PATCH/DELETE) on Deals."
        ),
        responses={
            200: DealResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: actor lacks access to this Deal.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Deal not found.",
            ),
        },
    )
    def get(self, request, deal_id):
        deal = (
            Deal.objects.filter(pk=deal_id)
            .select_related(
                "terms_snapshot",
                "terms_snapshot__commodity",
                "terms_snapshot__schema_version",
                "attribution",
            )
            .prefetch_related(
                "terms_snapshot__cost_snapshots",
                "party_snapshots",
                "broker_attributions",
                "broker_attributions__broker_organization",
                "broker_attributions__related_opportunity",
                "opportunity_attributions",
                "opportunity_attributions__opportunity",
            )
            .first()
        )
        if not deal:
            return Response(
                {"detail": f"Deal '{deal_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_deal_read_access(deal, request.user)
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = DealResponseSerializer(deal, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)



class DealTermsSnapshotView(APIView):
    """
    Retrieve immutable commercial terms snapshot for a Deal (Contract §13, §69, §98, T0902).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_terms_retrieve",
        tags=["Deals"],
        summary="Retrieve Deal Terms Snapshot",
        description=(
            "Retrieves the immutable accepted commercial terms snapshot of a Deal, "
            "including awarded quantity, unit price, currency, payment terms, delivery terms, "
            "Incoterm, logistics cost status, and child cost component snapshots. "
            "Strictly read-only; no mutation endpoints exist."
        ),
        responses={
            200: DealTermsSnapshotSerializer,
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: actor lacks access to this Deal.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Deal or terms snapshot not found.",
            ),
        },
    )
    def get(self, request, deal_id):
        deal = (
            Deal.objects.filter(pk=deal_id)
            .select_related("terms_snapshot")
            .prefetch_related("terms_snapshot__cost_snapshots")
            .first()
        )
        if not deal:
            return Response(
                {"detail": f"Deal '{deal_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_deal_read_access(deal, request.user)
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        try:
            terms = deal.terms_snapshot
        except Deal.terms_snapshot.RelatedObjectDoesNotExist:
            return Response(
                {"detail": f"Deal '{deal_id}' has no terms snapshot."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DealTermsSnapshotSerializer(terms)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DealPartiesSnapshotView(APIView):
    """
    Retrieve immutable principal party snapshots for a Deal (Contract §27-§32, §98, T0902).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_parties_list",
        tags=["Deals"],
        summary="List Deal Party Snapshots",
        description=(
            "Retrieves the immutable principal party snapshots (BUYER and SELLER) for a Deal. "
            "Enforces minimal commercial identity projection (names, countries, registration identifiers). "
            "Strictly read-only; no mutation endpoints exist."
        ),
        responses={
            200: OpenApiResponse(
                response=DealPartySnapshotSerializer(many=True),
                description="List of principal party snapshots (BUYER and SELLER).",
            ),
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: actor lacks access to this Deal.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Deal not found.",
            ),
        },
    )
    def get(self, request, deal_id):
        deal = Deal.objects.filter(pk=deal_id).prefetch_related("party_snapshots").first()
        if not deal:
            return Response(
                {"detail": f"Deal '{deal_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_deal_read_access(deal, request.user)
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        parties = deal.party_snapshots.all().order_by("role")
        serializer = DealPartySnapshotSerializer(parties, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DealAttributionDetailView(APIView):
    """
    Retrieve DealAttribution for a Deal (Contract §38, §78, §79, §98, T0903).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_attribution_retrieve",
        tags=["Deals"],
        summary="Retrieve Deal Attribution",
        description=(
            "Retrieves the DealAttribution record for a Deal. "
            "Customer actors (Buyer/Seller) receive a privacy-preserving projection "
            "where internal evidence_snapshot, resolved_by, and resolution_reason are withheld. "
            "Internal Platform Operators and Product Admins receive the complete provenance projection. "
            "Attributed Brokers who are not a commercial party receive 403 Forbidden."
        ),
        responses={
            200: DealAttributionSerializer,
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: actor lacks access to this Deal.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Deal or attribution not found.",
            ),
        },
    )
    def get(self, request, deal_id):
        deal = (
            Deal.objects.filter(pk=deal_id)
            .select_related("attribution")
            .prefetch_related(
                "broker_attributions",
                "broker_attributions__broker_organization",
                "broker_attributions__related_opportunity",
                "opportunity_attributions",
                "opportunity_attributions__opportunity",
            )
            .first()
        )
        if not deal:
            return Response(
                {"detail": f"Deal '{deal_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            _check_deal_read_access(deal, request.user)
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        try:
            attribution = deal.attribution
        except Deal.attribution.RelatedObjectDoesNotExist:
            return Response(
                {"detail": f"Deal '{deal_id}' has no attribution record."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DealAttributionSerializer(attribution, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class DealAttributionResolveView(APIView):
    """
    Manually resolve a PENDING DealAttribution (Contract §47, §101, T0903).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_attribution_resolve",
        tags=["Deals"],
        summary="Resolve Deal Attribution",
        description=(
            "Internal operational action to manually resolve a PENDING DealAttribution. "
            "Strictly restricted to Platform Operators and Product Admins via SystemRoleAssignment. "
            "Customer actors (Buyer, Supplier, Broker) and Django staff-only/superuser-only are denied. "
            "Requires primary_channel (one of 5 canonical categories) and resolution reason. "
            "Once RESOLVED, attribution becomes permanently immutable; subsequent attempts return 409 Conflict. "
            "Protected against concurrent races via PostgreSQL row-level locks and version checking."
        ),
        request=DealAttributionResolveRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=DealAttributionSerializer,
                description="Attribution successfully resolved.",
            ),
            400: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Validation error on input fields.",
            ),
            401: OpenApiResponse(description="Unauthenticated."),
            403: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Forbidden: only Platform Operators and Product Admins may resolve attribution.",
            ),
            404: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Deal or attribution not found.",
            ),
            409: OpenApiResponse(
                response=DealErrorResponseSerializer,
                description="Conflict: attribution is already resolved or version conflict.",
            ),
        },
    )
    def post(self, request, deal_id):
        if not _is_operator_or_admin(request.user):
            return Response(
                {"detail": "Only Platform Operators and Product Admins may manually resolve deal attribution."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DealAttributionResolveRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        primary_channel = serializer.validated_data["primary_channel"]
        reason = serializer.validated_data["reason"]
        expected_version = serializer.validated_data.get("expected_version")

        try:
            attribution = manual_resolve_deal_attribution(
                deal_id=deal_id,
                actor=request.user,
                primary_channel=primary_channel,
                reason=reason,
                expected_version=expected_version,
            )
        except DealPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except AttributionNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (AttributionAlreadyResolvedError, StaleVersionError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except DealValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        resp_serializer = DealAttributionSerializer(attribution, context={"request": request})
        return Response(resp_serializer.data, status=status.HTTP_200_OK)


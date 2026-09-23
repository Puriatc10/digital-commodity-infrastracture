from django.db import models
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from deals.api.serializers import (
    DealErrorResponseSerializer,
    DealMaterializeRequestSerializer,
    DealResponseSerializer,
)
from deals.exceptions import (
    AwardNotFinalizedError,
    AwardNotFoundError,
    DealPermissionDeniedError,
    DealSourceIntegrityError,
    DealValidationError,
    StaleVersionError,
)
from deals.models import Deal
from deals.services.materialization import (
    _is_operator_or_admin,
    materialize_deals_from_award,
)
from organizations.models import OrganizationMembership


class DealMaterializeActionView(APIView):
    """
    Authoritative Deal materialization domain action (Epic 9 Contract §10, §60, T0901).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_materialize",
        tags=["Deals"],
        summary="Materialize Deals from Finalized Award",
        description=(
            "Authoritatively materializes one immutable Deal aggregate per AwardAllocation "
            "from a finalized Award. "
            "Enforces server-side derivation of Buyer and Seller identities from authoritative "
            "source records without accepting client commercial fields. "
            "Guarantees idempotency: repeated calls return existing Deals without creating duplicates. "
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

        resp_serializer = DealResponseSerializer(deals, many=True)
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

        qs = qs.order_by("-created_at")
        serializer = DealResponseSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DealDetailView(APIView):
    """
    Retrieve minimal Deal aggregate by ID (Contract §76, §98, T0901).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deals_retrieve",
        tags=["Deals"],
        summary="Retrieve Deal by ID",
        description=(
            "Retrieves a minimal Deal aggregate by UUID. "
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
        deal = Deal.objects.filter(pk=deal_id).first()
        if not deal:
            return Response(
                {"detail": f"Deal '{deal_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _is_operator_or_admin(request.user):
            allowed_org_ids = [deal.buyer_organization_id]
            if deal.seller_organization_id:
                allowed_org_ids.append(deal.seller_organization_id)

            is_party_member = OrganizationMembership.objects.filter(
                user=request.user,
                organization_id__in=allowed_org_ids,
                is_active=True,
                organization__is_active=True,
            ).exists()

            if not is_party_member:
                return Response(
                    {"detail": "You do not have permission to access this deal."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = DealResponseSerializer(deal)
        return Response(serializer.data, status=status.HTTP_200_OK)

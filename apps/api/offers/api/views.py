from typing import Any
import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import SystemRoleAssignment
from offers.api.serializers import (
    OfferErrorResponseSerializer,
    OfferVersionResponseSerializer,
    OfferVersionSubmitActionSerializer,
)
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    OfferVersionNotFoundError,
    StaleVersionError,
)
from offers.models import OfferVersion
from offers.services.submission import submit_internal_offer_version
from organizations.models import OrganizationMembership


def _is_operator_or_admin(user: Any) -> bool:
    """Verify if user holds OPERATOR or ADMIN system authority."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


class OfferVersionSubmitActionView(APIView):
    """
    Authoritatively submit a Draft OfferVersion.

    Transitions the OfferVersion from DRAFT to SUBMITTED and if the target RFQ
    was in Published status, transitions it to Collecting Offers.
    Requires expected_version for optimistic concurrency control.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Submit draft OfferVersion",
        description=(
            "Transition a Draft OfferVersion to immutable SUBMITTED status. "
            "Revalidates dynamic commodity specifications against the exact RFQ schema version, "
            "quantity, unit, price, delivery dates, and logistics consistency. "
            "Revalidates organization capability and actor membership role (Owner, Manager, Member allowed; Viewer denied). "
            "Advances parent Offer aggregate_version and updates current_submitted_version pointer. "
            "Transitions target RFQ from Published to Collecting Offers upon first successful submission. "
            "Competitor participants attempting to access another organization's offer receive 404 Not Found."
        ),
        request=OfferVersionSubmitActionSerializer,
        responses={
            200: OfferVersionResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks submit role or capability"),
            404: OpenApiResponse(description="OfferVersion not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version or concurrent submission race"),
        },
    )
    def post(self, request, version_id):
        serializer = OfferVersionSubmitActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]

        # Server-side Competitor Privacy / IDOR Guard:
        # If the OfferVersion does not exist, or belongs to another organization and caller is not Operator,
        # return 404 Not Found with generic message to conceal competitor existence and version state.
        version_obj = (
            OfferVersion.objects.filter(pk=version_id)
            .select_related("offer")
            .first()
        )
        if not version_obj:
            return Response(
                {"detail": f"OfferVersion '{version_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _is_operator_or_admin(request.user):
            # Verify caller has active membership in the offering organization
            if not version_obj.offer.offering_organization_id:
                return Response(
                    {"detail": f"OfferVersion '{version_id}' does not exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            has_membership = OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=version_obj.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
            if not has_membership:
                return Response(
                    {"detail": f"OfferVersion '{version_id}' does not exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            submitted_version = submit_internal_offer_version(
                actor=request.user,
                offer_version=version_id,
                expected_version=expected_version,
                require_expected_version=True,
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (OfferVersionNotFoundError, OfferNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = OfferVersionResponseSerializer(submitted_version)
        return Response(out_serializer.data, status=status.HTTP_200_OK)

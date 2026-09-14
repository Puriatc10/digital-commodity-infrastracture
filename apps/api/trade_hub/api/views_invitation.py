from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from trade_hub.api.serializers_invitation import (
    RFQInvitationCreateSerializer,
    RFQInvitationDeclineSerializer,
    RFQInvitationResponseSerializer,
)
from trade_hub.exceptions import (
    DuplicateInvitationError,
    InvalidInvitationStatusError,
    InvalidTransitionError,
    InviteeIneligibleError,
    InvitationNotFoundError,
    InvitationPermissionDeniedError,
    RFQNotFoundError,
)
from trade_hub.services.invitation_service import (
    create_invitation,
    decline_invitation,
    get_invitation_detail,
    get_own_invitation,
    list_rfq_invitations,
    mark_invitation_viewed,
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


class RFQInvitationListCreateView(APIView):
    """
    List invited participants for an RFQ or invite a new organization.
    Access strictly restricted to the Buyer organization (Owner/Manager) or Platform Operators.
    Invited counterparties and competitors are prohibited from listing all participants.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List RFQ participants",
        description=(
            "Retrieve all invited participants for an RFQ. "
            "Strictly restricted to the RFQ Buyer organization (Owner/Manager) or Platform Operators. "
            "Competitors and invited suppliers receive 403 Forbidden."
        ),
        responses={
            200: RFQInvitationResponseSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(
                description="Forbidden - only RFQ buyer or operator can view participant list"
            ),
            404: OpenApiResponse(description="RFQ not found"),
        },
    )
    def get(self, request, rfq_id):
        org_hint = _get_org_hint(request)
        try:
            invitations = list_rfq_invitations(
                rfq_id, request.user, organization_hint=org_hint
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except InvitationPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = RFQInvitationResponseSerializer(invitations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Invite organization to RFQ",
        description=(
            "Invite a verified Supplier or Broker organization to participate in an RFQ. "
            "Restricted to Buyer Owner/Manager or Platform Operator. "
            "Cannot invite Buyer-only organizations or the RFQ owner. "
            "Cannot invite to Closed or Cancelled RFQs."
        ),
        request=RFQInvitationCreateSerializer,
        responses={
            201: RFQInvitationResponseSerializer,
            400: OpenApiResponse(description="Invalid request or ineligible invitee"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks invite permission"),
            404: OpenApiResponse(description="RFQ or target organization not found"),
            409: OpenApiResponse(
                description="Conflict - organization is already invited"
            ),
        },
    )
    def post(self, request, rfq_id):
        serializer = RFQInvitationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org_hint = _get_org_hint(request)
        target_org_id = serializer.validated_data["organization_id"]
        expires_at = serializer.validated_data.get("expires_at")

        try:
            invitation = create_invitation(
                rfq_or_id=rfq_id,
                target_org_or_id=target_org_id,
                user=request.user,
                organization_hint=org_hint,
                expires_at=expires_at,
            )
        except RFQNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except InvitationPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except InviteeIneligibleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DuplicateInvitationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        out_serializer = RFQInvitationResponseSerializer(invitation)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class RFQInvitationMeView(APIView):
    """
    Retrieve the current organization's own invitation record for an RFQ.
    Allows invited suppliers/brokers to inspect their own participation status without
    exposing other participants or competitors.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get own RFQ invitation",
        description=(
            "Retrieve the caller organization's own invitation for this RFQ. "
            "Provides competitor isolation: returns 404 if the organization is not invited."
        ),
        responses={
            200: RFQInvitationResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(
                description="No invitation found for current organization"
            ),
        },
    )
    def get(self, request, rfq_id):
        org_hint = _get_org_hint(request)
        try:
            invitation = get_own_invitation(
                rfq_id, request.user, organization_hint=org_hint
            )
        except (RFQNotFoundError, InvitationNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        serializer = RFQInvitationResponseSerializer(invitation)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RFQInvitationDetailView(APIView):
    """
    Retrieve detail of a specific invitation record.
    Accessible only to the Buyer organization, the invited organization, or Platform Operators.
    Hidden (404) to competitors and unauthorized parties.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get invitation detail",
        description="Retrieve a specific invitation record. Hidden (404) to competitors.",
        responses={
            200: RFQInvitationResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Invitation not found or hidden"),
        },
    )
    def get(self, request, rfq_id, invitation_id):
        org_hint = _get_org_hint(request)
        try:
            invitation = get_invitation_detail(
                invitation_id, request.user, organization_hint=org_hint
            )
            if str(invitation.rfq_id) != str(rfq_id):
                return Response(
                    {"detail": "Invitation does not belong to this RFQ."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        except InvitationNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        serializer = RFQInvitationResponseSerializer(invitation)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RFQInvitationViewActionView(APIView):
    """
    Mark an invitation as viewed when opened by the invited organization.
    Advances status from 'invited' to 'viewed' and records viewed_at timestamp.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Mark invitation viewed",
        description="Record that the invited organization has viewed the RFQ invitation.",
        request=None,
        responses={
            200: RFQInvitationResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Invitation not found or hidden"),
        },
    )
    def post(self, request, rfq_id, invitation_id):
        org_hint = _get_org_hint(request)
        try:
            invitation = mark_invitation_viewed(
                invitation_id, request.user, organization_hint=org_hint
            )
            if str(invitation.rfq_id) != str(rfq_id):
                return Response(
                    {"detail": "Invitation does not belong to this RFQ."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        except InvitationNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        serializer = RFQInvitationResponseSerializer(invitation)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RFQInvitationDeclineActionView(APIView):
    """
    Decline an RFQ invitation.
    Permitted only to the Owner or Manager of the invited organization (or Platform Operator).
    Revokes Private RFQ visibility for the declining organization.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Decline RFQ invitation",
        description="Decline an RFQ invitation. Revokes visibility to Private RFQs.",
        request=RFQInvitationDeclineSerializer,
        responses={
            200: RFQInvitationResponseSerializer,
            400: OpenApiResponse(
                description="Invalid request or invitation already expired"
            ),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(
                description="Forbidden - only invitee Owner/Manager can decline"
            ),
            404: OpenApiResponse(description="Invitation not found or hidden"),
        },
    )
    def post(self, request, rfq_id, invitation_id):
        serializer = RFQInvitationDeclineSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org_hint = _get_org_hint(request)
        reason = serializer.validated_data.get("reason", "")

        try:
            invitation = decline_invitation(
                invitation_id,
                request.user,
                reason=reason,
                organization_hint=org_hint,
            )
            if str(invitation.rfq_id) != str(rfq_id):
                return Response(
                    {"detail": "Invitation does not belong to this RFQ."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        except InvitationNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except InvitationPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except InvalidInvitationStatusError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = RFQInvitationResponseSerializer(invitation)
        return Response(out_serializer.data, status=status.HTTP_200_OK)

import logging
import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from matching.api.serializers import (
    MatchingCandidateResponseSerializer,
    MatchingErrorResponseSerializer,
    MatchingRunCreateSerializer,
    MatchingRunResponseSerializer,
)
from matching.candidates.authorization import (
    has_global_matching_authority,
    is_active_organization_member,
    resolve_actor_scope,
)
from matching.enums import CandidateLane, MatchingAudience
from matching.exceptions import (
    HistoricalProviderError,
    InvalidPolicyConfigurationError,
    MatchingAuthorizationError,
    NoPublishedPolicyError,
    RFQNotMatchableError,
    RFQNotFoundError,
    UnsupportedAudienceError,
)

from matching.models.candidate import MatchingCandidate
from matching.models.run import MatchingRun
from matching.services import MatchingRunService
from trade_hub.models import RFQ

logger = logging.getLogger(__name__)


def _get_org_hint(request):
    return (
        getattr(request, "current_organization", None)
        or getattr(request, "organization", None)
        or (request.session.get("organization_id") if hasattr(request, "session") else None)
        or (request.headers.get("X-Organization-Id") if hasattr(request, "headers") else None)
        or (request.query_params.get("organization") if hasattr(request, "query_params") else None)
    )


class RFQMatchingRunListCreateView(APIView):
    """
    Execute a new deterministic matching run for an RFQ or list historical runs for this RFQ.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Trigger a Matching Run for an RFQ",
        description=(
            "Executes an audience-scoped, deterministic matching run against a Published RFQ target. "
            "Evaluates Direct Supply, Potential Supplier, and Broker Path lanes with 3-part Decimal scoring "
            "(Fit Score, Evidence Coverage, Ranking Score) and lane-local ranking."
        ),
        request=MatchingRunCreateSerializer,
        responses={
            201: MatchingRunResponseSerializer,
            400: MatchingErrorResponseSerializer,
            403: MatchingErrorResponseSerializer,
            404: MatchingErrorResponseSerializer,
            500: MatchingErrorResponseSerializer,
        },
    )
    def post(self, request, rfq_id: uuid.UUID):
        serializer = MatchingRunCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"code": "invalid_parameters", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        audience = serializer.validated_data.get("audience", MatchingAudience.BUYER)
        policy_version_id = serializer.validated_data.get("policy_version_id")

        actor_scope = resolve_actor_scope(request.user, organization=_get_org_hint(request))

        try:
            run = MatchingRunService.execute_matching_run(
                rfq_id=rfq_id,
                audience=audience,
                actor_scope=actor_scope,
                policy_version_id=policy_version_id,
            )
        except RFQNotFoundError as e:
            return Response({"code": e.code, "detail": e.message}, status=status.HTTP_404_NOT_FOUND)
        except RFQNotMatchableError as e:
            return Response({"code": e.code, "detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        except MatchingAuthorizationError as e:
            return Response({"code": e.code, "detail": e.message}, status=status.HTTP_403_FORBIDDEN)
        except (NoPublishedPolicyError, UnsupportedAudienceError, InvalidPolicyConfigurationError) as e:
            return Response({"code": e.code, "detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        except HistoricalProviderError as e:
            logger.error(
                "Historical provider failure during matching run: rfq_id=%s, audience=%s, provider=%s",
                rfq_id,
                audience,
                getattr(e, "provider_code", "unknown"),
            )
            return Response(
                {
                    "code": e.code,
                    "detail": "A historical signal provider encountered an operational failure.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response_data = MatchingRunResponseSerializer(run).data
        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="List Historical Matching Runs for an RFQ",
        description="Retrieve historical matching execution runs for an authorized RFQ target.",
        responses={
            200: MatchingRunResponseSerializer(many=True),
            403: MatchingErrorResponseSerializer,
            404: MatchingErrorResponseSerializer,
        },
    )
    def get(self, request, rfq_id: uuid.UUID):
        rfq = RFQ.objects.filter(pk=rfq_id).first()
        if not rfq:
            return Response(
                {"code": "not_found_or_hidden", "detail": "RFQ not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_op_or_admin = has_global_matching_authority(request.user)
        is_owner_member = is_active_organization_member(request.user, rfq.organization_id)

        if not (is_op_or_admin or is_owner_member):
            return Response(
                {"code": "unauthorized", "detail": "You do not have access to matching intelligence for this RFQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = MatchingRun.objects.filter(rfq=rfq).select_related("rfq", "policy_version")
        if not is_op_or_admin:
            # Buyer can only see runs generated under BUYER audience scope
            qs = qs.filter(audience=MatchingAudience.BUYER)

        serializer = MatchingRunResponseSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MatchingRunDetailView(APIView):
    """Retrieve metadata and execution summary for a specific MatchingRun."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retrieve Matching Run Details",
        description="Retrieve metadata, staleness, policy version, and fingerprints for a matching execution run.",
        responses={
            200: MatchingRunResponseSerializer,
            403: MatchingErrorResponseSerializer,
            404: MatchingErrorResponseSerializer,
        },
    )
    def get(self, request, run_id: uuid.UUID):
        run = MatchingRun.objects.select_related("rfq", "policy_version").filter(pk=run_id).first()
        if not run:
            return Response(
                {"code": "not_found", "detail": "MatchingRun not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_op_or_admin = has_global_matching_authority(request.user)
        if run.audience == MatchingAudience.OPERATOR and not is_op_or_admin:
            return Response(
                {"code": "unauthorized", "detail": "Operator or Admin system authority required for Operator run."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if run.audience == MatchingAudience.BUYER:
            if not is_op_or_admin and not is_active_organization_member(request.user, run.rfq.organization_id):
                return Response(
                    {"code": "unauthorized", "detail": "You do not have access to this MatchingRun."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = MatchingRunResponseSerializer(run)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MatchingRunCandidateListView(APIView):
    """
    List evaluated candidates for a specific MatchingRun.
    Supports lane filtering and returns audience-safe source projections.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List Candidates for a Matching Run",
        description=(
            "Retrieve evaluated candidates with lane ranking, 3-part Decimal scores, "
            "safe source projection, and structured explainability signals."
        ),
        parameters=[
            OpenApiParameter(
                name="lane",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=CandidateLane.values,
                description="Filter candidates by lane (DIRECT_SUPPLY, POTENTIAL_SUPPLIER, BROKER_PATH).",
            ),
            OpenApiParameter(
                name="eligible",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by candidate eligibility status.",
            ),
        ],
        responses={
            200: MatchingCandidateResponseSerializer(many=True),
            403: MatchingErrorResponseSerializer,
            404: MatchingErrorResponseSerializer,
        },
    )
    def get(self, request, run_id: uuid.UUID):
        run = MatchingRun.objects.select_related("rfq").filter(pk=run_id).first()
        if not run:
            return Response(
                {"code": "not_found", "detail": "MatchingRun not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_op_or_admin = has_global_matching_authority(request.user)
        if run.audience == MatchingAudience.OPERATOR and not is_op_or_admin:
            return Response(
                {"code": "unauthorized", "detail": "Operator or Admin authority required for Operator runs."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if run.audience == MatchingAudience.BUYER:
            if not is_op_or_admin and not is_active_organization_member(request.user, run.rfq.organization_id):
                return Response(
                    {"code": "unauthorized", "detail": "Access to matching candidate intelligence denied."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        qs = (
            MatchingCandidate.objects.filter(run=run)
            .select_related(
                "supply_listing__organization",
                "supplier_organization",
                "broker_organization",
                "supply_opportunity",
            )
            .prefetch_related("signals")
            .order_by("lane", "rank", "-ranking_score", "id")
        )

        lane = request.query_params.get("lane")
        if lane:
            qs = qs.filter(lane=lane)

        eligible_param = request.query_params.get("eligible")
        if eligible_param is not None:
            is_el = eligible_param.lower() in ("true", "1", "yes")
            qs = qs.filter(eligible=is_el)

        serializer = MatchingCandidateResponseSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

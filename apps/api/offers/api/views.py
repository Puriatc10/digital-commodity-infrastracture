from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import SystemRoleAssignment
from offers.api.serializers import (
    BuyerOfferProjectionResponseSerializer,
    OfferErrorResponseSerializer,
    OfferVersionResponseSerializer,
    OfferVersionSubmitActionSerializer,
    OperatorExternalOfferSubmissionSerializer,
    OperatorOfferDetailResponseSerializer,
    OperatorRFQComparisonResponseSerializer,
    RFQComparisonResponseSerializer,
)
from offers.enums import LogisticsCostStatus
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
from offers.models import Offer, OfferVersion
from offers.services.comparison import compare_rfq_offers
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.submission import submit_internal_offer_version
from organizations.models import OrganizationMembership
from trade_hub.models import RFQ


def _is_operator_or_admin(user: Any) -> bool:
    """Verify if user holds OPERATOR or ADMIN system authority."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
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


class OperatorExternalOfferSubmissionActionView(APIView):
    """
    Authoritative Operator Submission on Behalf action (T0804 / T0611).

    Allows platform Operators or Product Admins to enter an external supplier quote
    from a Qualified Supply Opportunity directly onto an RFQ.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Submit external supplier offer on behalf (Operator action)",
        description=(
            "Enters an external supplier quote from a Qualified Supply Opportunity onto an RFQ. "
            "Authorized exclusively for platform Operators and Product Admins (via SystemRoleAssignment). "
            "Buyer, Supplier, Broker organizations and staff/superuser without product roles are rejected. "
            "Guarantees atomic execution, derives external economic party from the Opportunity, "
            "enforces RFQ deadline and lifecycle, dynamic specification schema lock, and immutability."
        ),
        request=OperatorExternalOfferSubmissionSerializer,
        responses={
            201: OfferVersionResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - Operator or Product Admin role required"),
            404: OpenApiResponse(description="RFQ or Opportunity not found"),
            409: OpenApiResponse(description="Conflict - existing submitted version or concurrency race"),
        },
    )
    def post(self, request, rfq_id=None):
        # 1. Authorization & Side-channel Guard:
        # Non-operators immediately receive 403 Forbidden before evaluating Opportunity or RFQ existence
        if not _is_operator_or_admin(request.user):
            return Response(
                {"detail": "Only platform Operators and Product Admins may submit offers on behalf of external counterparties."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if rfq_id and not data.get("rfq_id"):
            data["rfq_id"] = str(rfq_id)

        serializer = OperatorExternalOfferSubmissionSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data

        try:
            offer, submitted_version = submit_operator_external_offer(
                actor=request.user,
                rfq=validated["rfq_id"],
                opportunity=validated["opportunity_id"],
                offered_quantity=validated["offered_quantity"],
                quantity_unit=validated["quantity_unit"],
                unit_price=validated["unit_price"],
                currency=validated.get("currency", "USD"),
                payment_terms=validated.get("payment_terms", ""),
                delivery_terms=validated.get("delivery_terms", ""),
                incoterm=validated.get("incoterm", ""),
                delivery_start=validated.get("delivery_start"),
                delivery_end=validated.get("delivery_end"),
                valid_until=validated.get("valid_until"),
                logistics_cost_status=validated.get("logistics_cost_status", LogisticsCostStatus.UNKNOWN),
                logistics_cost_amount=validated.get("logistics_cost_amount"),
                specifications=validated.get("specifications"),
                notes=validated.get("notes", ""),
                cost_components=validated.get("cost_components"),
                external_counterparty=validated.get("external_counterparty_id"),
                expected_version=validated.get("expected_version"),
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except OfferNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OfferVersionResponseSerializer(submitted_version).data, status=status.HTTP_201_CREATED)


class OfferDetailView(APIView):
    """
    Retrieve details of an Offer.

    Enforces strict privacy projections:
    - Operator/Admin: receives complete operational projection (including Opportunity/Broker provenance).
    - RFQ Buyer: receives safe commercial projection (excluding CRM, phone, email, notes).
    - Offering Organization: receives commercial projection of own offer.
    - Competitor Supplier/Broker: returns 404 Not Found (concealing competitor presence).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get Offer details",
        description=(
            "Retrieves an Offer by ID. Authorized for platform Operators, Admins, and the owning RFQ Buyer. "
            "Competitors attempting to access another party's offer receive 404 Not Found."
        ),
        responses={
            200: OpenApiResponse(description="Offer details (Operator or Buyer projection)"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Offer not found or inaccessible"),
        },
    )
    def get(self, request, offer_id):
        offer = (
            Offer.objects.filter(pk=offer_id)
            .select_related(
                "rfq",
                "offering_organization",
                "external_counterparty",
                "source_opportunity",
                "current_submitted_version",
            )
            .first()
        )
        if not offer:
            return Response(
                {"detail": f"Offer '{offer_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 1. Platform Operator / Admin: full operational projection
        if _is_operator_or_admin(request.user):
            serializer = OperatorOfferDetailResponseSerializer(offer)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # 2. RFQ Buyer: safe commercial projection
        is_rfq_buyer = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        if is_rfq_buyer:
            if not offer.current_submitted_version_id:
                return Response(
                    {"detail": f"Offer '{offer_id}' does not exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            serializer = BuyerOfferProjectionResponseSerializer(offer)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # 3. Offering Organization: own offer projection
        if offer.offering_organization_id:
            is_offeror_member = OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
            if is_offeror_member:
                serializer = BuyerOfferProjectionResponseSerializer(offer)
                return Response(serializer.data, status=status.HTTP_200_OK)

        # 4. Competitor participant denial: return generic 404 Not Found
        return Response(
            {"detail": f"Offer '{offer_id}' does not exist."},
            status=status.HTTP_404_NOT_FOUND,
        )


class RFQOffersListView(APIView):
    """
    List submitted offers for a given RFQ.

    Accessible to:
    - Platform Operators and Product Admins
    - RFQ Buyer Organization members
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List offers for an RFQ",
        description=(
            "Lists all submitted offers for an RFQ. "
            "Authorized for RFQ Buyer organization members and platform Operators/Admins."
        ),
        responses={
            200: OpenApiResponse(description="List of offers for this RFQ"),
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks access to this RFQ"),
            404: OpenApiResponse(description="RFQ not found"),
        },
    )
    def get(self, request, rfq_id):
        rfq = RFQ.objects.filter(pk=rfq_id).first()
        if not rfq:
            return Response(
                {"detail": f"RFQ '{rfq_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if _is_operator_or_admin(request.user):
            qs = (
                Offer.objects.filter(rfq=rfq)
                .select_related(
                    "external_counterparty",
                    "offering_organization",
                    "source_opportunity",
                    "current_submitted_version",
                )
                .order_by("-created_at")
            )
            serializer = OperatorOfferDetailResponseSerializer(qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        is_rfq_buyer = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        if is_rfq_buyer:
            qs = (
                Offer.objects.filter(rfq=rfq, current_submitted_version__isnull=False)
                .select_related(
                    "external_counterparty",
                    "offering_organization",
                    "current_submitted_version",
                )
                .order_by("-created_at")
            )
            serializer = BuyerOfferProjectionResponseSerializer(qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(
            {"detail": "You do not have permission to view offers for this RFQ."},
            status=status.HTTP_403_FORBIDDEN,
        )


class RFQComparisonView(APIView):
    """
    Commercial Offer Comparison API for an RFQ (T0806).

    Exposes structured, side-by-side commercial proposals for an RFQ across all Offer threads.
    Evaluates each Offer thread's current submitted version only (drafts and older superseded
    versions are excluded from active comparison rows).

    Authorization:
    - Allowed:
      - Authorized Buyer procurement actors (active membership in owning RFQ Organization)
      - Platform Operators and Product Admins (via SystemRoleAssignment)
    - Explicitly Rejected:
      - Supplier / Broker participants attempting to access competitor comparison (403 Forbidden)
      - Foreign Buyer organizations (403 Forbidden)
      - Django staff/superuser without SystemRoleAssignment or Buyer membership (403 Forbidden)
      - Anonymous callers (401 Unauthorized)

    Invariants:
    - Pure comparison; zero decision support scoring or recommendations.
    - Neutral deterministic ordering (by created_at, id); no sorting by price or landed cost.
    - Preserves submitted currencies; flags cross-currency as CROSS_CURRENCY_UNKNOWN without FX.
    - Distinguishes unknown logistics from zero extra cost.
    - Protects counterparty privacy: Buyer projection contains safe commercial identity only;
      phone, email, notes, and private opportunity sourcing details are strictly excluded.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Commercial comparison of submitted offers for an RFQ",
        description=(
            "Retrieves the commercial comparison of all currently active submitted offers for an RFQ. "
            "Evaluates only Offer.current_submitted_version for each offer thread. "
            "Excludes unsubmitted drafts and older versions. "
            "Reuses T0805 normalisation engine and derives quantity coverage and surplus. "
            "Authorized exclusively for the RFQ's Buyer organization members and platform Operators/Admins. "
            "Competitor participants (Suppliers/Brokers) and foreign buyers are strictly rejected."
        ),
        responses={
            200: RFQComparisonResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="RFQ not found"),
        },
    )
    def get(self, request, rfq_id):
        rfq = (
            RFQ.objects.filter(pk=rfq_id)
            .select_related("schema_version", "organization")
            .first()
        )
        if not rfq:
            return Response(
                {"detail": f"RFQ '{rfq_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)

        # Buyer authorization check: active membership in the RFQ's owning Buyer organization
        is_rfq_buyer = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()

        if not is_operator and not is_rfq_buyer:
            return Response(
                {"detail": "You do not have permission to view commercial comparison for this RFQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        comparison = compare_rfq_offers(
            rfq,
            actor=request.user,
            is_operator=is_operator,
        )

        if is_operator:
            serializer = OperatorRFQComparisonResponseSerializer(comparison.to_dict())
        else:
            serializer = RFQComparisonResponseSerializer(comparison.to_dict())

        return Response(serializer.data, status=status.HTTP_200_OK)


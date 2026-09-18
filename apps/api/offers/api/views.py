from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import SystemRoleAssignment
from offers.api.serializers import (
    BuyerOfferProjectionResponseSerializer,
    DecisionRunCreateRequestSerializer,
    DecisionRunDetailResponseSerializer,
    OfferErrorResponseSerializer,
    OfferVersionResponseSerializer,
    OfferVersionSubmitActionSerializer,
    OperatorExternalOfferSubmissionSerializer,
    OperatorOfferDetailResponseSerializer,
    OperatorRFQComparisonResponseSerializer,
    RFQComparisonResponseSerializer,
    RevisionRequestActionSerializer,
    RevisionRequestCreateSerializer,
    RevisionRequestDraftCreateSerializer,
    RevisionRequestResponseSerializer,
    RevisionRequestSubmitSerializer,
)
from offers.enums import LogisticsCostStatus
from offers.exceptions import (
    DecisionPermissionDeniedError,
    DecisionPolicyError,
    DecisionValidationError,
    InvalidVersionError,
    OfferConflictError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    OfferVersionNotFoundError,
    RevisionRequestNotFoundError,
    StaleVersionError,
)
from offers.models import (
    DecisionProfileVersion,
    DecisionRun,
    Offer,
    OfferVersion,
    RevisionRequest,
)
from offers.services.comparison import compare_rfq_offers
from offers.services.decision_service import (
    execute_decision_run_pipeline,
)
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.revision_service import (
    cancel_revision_request,
    create_revised_draft_offer_version,
    create_revision_request,
    decline_revision_request,
    submit_revised_offer_version,
)
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

        rev_req_id = serializer.validated_data.get("revision_request")
        try:
            if rev_req_id:
                submitted_version, _ = submit_revised_offer_version(
                    actor=request.user,
                    revision_request=rev_req_id,
                    draft_version=version_id,
                    expected_version=expected_version,
                )
            else:
                submitted_version = submit_internal_offer_version(
                    actor=request.user,
                    offer_version=version_id,
                    expected_version=expected_version,
                    require_expected_version=True,
                )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (OfferVersionNotFoundError, OfferNotFoundError, RevisionRequestNotFoundError) as exc:
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


class RFQDecisionRunCreateView(APIView):
    """
    Initiate an immutable DecisionRun foundation execution for an RFQ (T0808).

    Evaluates the current submitted version per Offer thread using T0806 comparison universe
    under the specified or default Published DecisionProfileVersion.

    Authorization:
    - Allowed: RFQ Buyer Organization members and platform Operators/Admins.
    - Explicitly Rejected: Competitor participants (Suppliers/Brokers), foreign buyers,
      staff-only, anonymous callers.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Create DecisionRun foundation for an RFQ",
        description=(
            "Initiate an immutable DecisionRun foundation for the specified RFQ. "
            "Materializes current submitted OfferVersions as DecisionCandidates and "
            "computes a deterministic canonical input fingerprint. "
            "Authorized exclusively for the RFQ's Buyer organization and platform Operators/Admins."
        ),
        request=DecisionRunCreateRequestSerializer,
        responses={
            201: DecisionRunDetailResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="RFQ or DecisionProfileVersion not found"),
        },
    )
    def post(self, request, rfq_id):
        serializer = DecisionRunCreateRequestSerializer(data=request.data or {})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        profile_version_id = serializer.validated_data.get("profile_version_id")
        profile_version = None
        if profile_version_id:
            profile_version = DecisionProfileVersion.objects.filter(pk=profile_version_id).first()
            if not profile_version:
                return Response(
                    {"detail": f"DecisionProfileVersion '{profile_version_id}' does not exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            run = execute_decision_run_pipeline(
                rfq=rfq_id,
                actor=request.user,
                profile_version=profile_version,
            )
        except OfferNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DecisionPermissionDeniedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except (DecisionPolicyError, DecisionValidationError, OfferValidationError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Reload with related fields for response serialization
        run_loaded = (
            DecisionRun.objects.filter(pk=run.pk)
            .select_related("rfq", "decision_profile_version", "decision_profile_version__profile")
            .prefetch_related(
                "candidates",
                "candidates__offer_version",
                "candidates__signals",
            )
            .first()
        )
        response_serializer = DecisionRunDetailResponseSerializer(run_loaded)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Retrieve latest DecisionRun for an RFQ",
        description=(
            "Retrieves the most recent DecisionRun for the specified RFQ. "
            "Authorized exclusively for the RFQ's Buyer organization and platform Operators/Admins. "
            "Returns 404 if no DecisionRun has been executed for this RFQ yet."
        ),
        responses={
            200: DecisionRunDetailResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="RFQ or DecisionRun not found"),
        },
    )
    def get(self, request, rfq_id):
        rfq = RFQ.objects.filter(pk=rfq_id).first()
        if not rfq:
            return Response(
                {"detail": f"RFQ '{rfq_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_rfq_buyer = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()

        if not is_operator and not is_rfq_buyer:
            return Response(
                {"detail": "You do not have permission to view decision intelligence for this RFQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        run = (
            DecisionRun.objects.filter(rfq=rfq)
            .select_related("rfq", "decision_profile_version", "decision_profile_version__profile")
            .prefetch_related(
                "candidates",
                "candidates__offer_version",
                "candidates__signals",
            )
            .order_by("-created_at")
            .first()
        )
        if not run:
            return Response(
                {"detail": f"No DecisionRun found for RFQ '{rfq_id}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DecisionRunDetailResponseSerializer(run)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DecisionRunDetailView(APIView):
    """
    Retrieve an immutable DecisionRun audit record and its materialized candidates (T0808).

    Authorization:
    - Allowed: RFQ Buyer Organization members and platform Operators/Admins.
    - Explicitly Rejected: Competitor participants (Suppliers/Brokers), foreign buyers,
      staff-only, anonymous callers.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retrieve DecisionRun detail",
        description=(
            "Retrieves an immutable DecisionRun and its candidate universe. "
            "Authorized exclusively for the RFQ's Buyer organization and platform Operators/Admins. "
            "Competitor participants (Suppliers/Brokers) cannot access decision intelligence."
        ),
        responses={
            200: DecisionRunDetailResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="DecisionRun not found"),
        },
    )
    def get(self, request, run_id):
        run = (
            DecisionRun.objects.filter(pk=run_id)
            .select_related("rfq", "decision_profile_version", "decision_profile_version__profile")
            .prefetch_related(
                "candidates",
                "candidates__offer_version",
                "candidates__signals",
            )
            .first()
        )
        if not run:
            return Response(
                {"detail": f"DecisionRun '{run_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_rfq_buyer = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=run.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()

        if not is_operator and not is_rfq_buyer:
            return Response(
                {"detail": "You do not have permission to view decision intelligence for this RFQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DecisionRunDetailResponseSerializer(run)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OfferRevisionRequestCreateView(APIView):
    """
    Open or list RevisionRequests for a specific Offer (T0810, Contract §56).

    POST: Authoritatively open a RevisionRequest against the Offer's current submitted version.
    Authorized for Buyer procurement actors (Owner/Manager of RFQ Buyer org) and platform Operators.
    Supplier/Broker participants attempting to create revision requests receive 403 Forbidden.
    Competitors receive 404 Not Found to conceal offer existence.

    GET: List revision requests for the offer.
    Accessible to RFQ Buyer, offering party, and platform Operators.
    Competitors receive 404 Not Found.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Create offer revision request",
        description=(
            "Open a formal RevisionRequest against the current submitted OfferVersion. "
            "Requires expected_version for optimistic concurrency control on the Offer aggregate. "
            "Authorized for Buyer organization Owner/Manager or platform Operator. "
            "Transitions target RFQ from Collecting Offers to Negotiating upon first revision request. "
            "Competitors attempting to access or request revisions receive 404 Not Found."
        ),
        request=RevisionRequestCreateSerializer,
        responses={
            201: RevisionRequestResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="Offer or base OfferVersion not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version or already open revision request"),
        },
    )
    def post(self, request, offer_id):
        offer = (
            Offer.objects.filter(pk=offer_id)
            .select_related("rfq", "offering_organization")
            .first()
        )
        if not offer:
            return Response(
                {"detail": f"Offer '{offer_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        # IDOR / Privacy guard: competitors receive 404
        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"Offer '{offer_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Supplier self-request guard: offering organization members cannot request revision on own offer
        if is_offeror_member and not (is_operator or is_buyer_member):
            return Response(
                {"detail": "Suppliers and Brokers cannot issue revision requests to their own offers."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RevisionRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        try:
            rev_req = create_revision_request(
                actor=request.user,
                offer=offer,
                base_offer_version=validated["base_offer_version"],
                requested_fields=validated["requested_fields"],
                message=validated.get("message", ""),
                expected_version=validated["expected_version"],
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (OfferNotFoundError, OfferVersionNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out_serializer = RevisionRequestResponseSerializer(rev_req)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="List offer revision requests",
        description=(
            "List all revision requests for a specific Offer. "
            "Authorized for RFQ Buyer, offering party, and platform Operators. "
            "Competitors receive 404 Not Found."
        ),
        responses={
            200: RevisionRequestResponseSerializer(many=True),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Offer not found or inaccessible"),
        },
    )
    def get(self, request, offer_id):
        offer = (
            Offer.objects.filter(pk=offer_id)
            .select_related("rfq", "offering_organization")
            .first()
        )
        if not offer:
            return Response(
                {"detail": f"Offer '{offer_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"Offer '{offer_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        requests = (
            RevisionRequest.objects.filter(offer=offer)
            .select_related("offer", "base_offer_version")
            .order_by("-requested_at")
        )
        serializer = RevisionRequestResponseSerializer(requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RevisionRequestDeclineView(APIView):
    """
    Decline an open RevisionRequest (T0810, Contract §56).

    Authorized exclusively for the actor representing the Offer economic party:
    - Internal: Supplier/Broker organization authorized member (Owner, Manager, Member; Viewer denied).
    - External: Platform Operator / Product Admin on behalf of external counterparty.
    Buyer-side actors cannot decline.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Decline open revision request",
        description=(
            "Decline an OPEN RevisionRequest. Requires expected_version for optimistic concurrency. "
            "Authorized exclusively for the Offer economic party representative (Supplier/Broker member "
            "or Operator for external counterparty). Buyers cannot decline."
        ),
        request=RevisionRequestActionSerializer,
        responses={
            200: RevisionRequestResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - actor does not represent Offer economic party"),
            404: OpenApiResponse(description="RevisionRequest not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version or request not in OPEN status"),
        },
    )
    def post(self, request, request_id):
        rev_req = (
            RevisionRequest.objects.filter(pk=request_id)
            .select_related("offer", "offer__rfq")
            .first()
        )
        if not rev_req:
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rev_req.offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            rev_req.offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=rev_req.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if is_buyer_member and not (is_operator or is_offeror_member):
            return Response(
                {"detail": "Buyer procurement actors cannot decline revision requests; only the Offer economic party may decline."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RevisionRequestActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]

        try:
            declined_req = decline_revision_request(
                actor=request.user,
                revision_request=rev_req,
                expected_version=expected_version,
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (RevisionRequestNotFoundError, OfferNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(RevisionRequestResponseSerializer(declined_req).data, status=status.HTTP_200_OK)


class RevisionRequestCancelView(APIView):
    """
    Cancel an open RevisionRequest (T0810, Contract §56).

    Authorized for Buyer procurement actors (Owner/Manager of RFQ Buyer org) or platform Operators.
    Offer participants (Supplier/Broker) cannot cancel Buyer's request.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Cancel open revision request",
        description=(
            "Cancel an OPEN RevisionRequest. Requires expected_version for optimistic concurrency. "
            "Authorized for Buyer procurement actors or platform Operators. "
            "Offer participants cannot cancel Buyer's request."
        ),
        request=RevisionRequestActionSerializer,
        responses={
            200: RevisionRequestResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - actor lacks Buyer procurement role or Operator authority"),
            404: OpenApiResponse(description="RevisionRequest not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version or request not in OPEN status"),
        },
    )
    def post(self, request, request_id):
        rev_req = (
            RevisionRequest.objects.filter(pk=request_id)
            .select_related("offer", "offer__rfq")
            .first()
        )
        if not rev_req:
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rev_req.offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            rev_req.offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=rev_req.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if is_offeror_member and not (is_operator or is_buyer_member):
            return Response(
                {"detail": "Offer participants cannot cancel Buyer's revision request."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RevisionRequestActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]

        try:
            cancelled_req = cancel_revision_request(
                actor=request.user,
                revision_request=rev_req,
                expected_version=expected_version,
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (RevisionRequestNotFoundError, OfferNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(RevisionRequestResponseSerializer(cancelled_req).data, status=status.HTTP_200_OK)


class RevisionRequestDetailView(APIView):
    """
    Retrieve details of a RevisionRequest (T0810, Contract §56).

    Authorized for RFQ Buyer, offering party, and platform Operators.
    Competitors receive 404 Not Found.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get revision request details",
        description=(
            "Retrieve details of a RevisionRequest by ID. "
            "Authorized for RFQ Buyer, offering party, and platform Operators. "
            "Competitors receive 404 Not Found."
        ),
        responses={
            200: RevisionRequestResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="RevisionRequest not found or inaccessible"),
        },
    )
    def get(self, request, request_id):
        rev_req = (
            RevisionRequest.objects.filter(pk=request_id)
            .select_related("offer", "offer__rfq", "base_offer_version")
            .first()
        )
        if not rev_req:
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rev_req.offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            rev_req.offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=rev_req.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = RevisionRequestResponseSerializer(rev_req)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RevisionRequestCreateDraftView(APIView):
    """
    Create a Draft OfferVersion from an OPEN RevisionRequest (T0811).

    Authorized for the Offer economic party representative:
    - Internal: Offering organization member (Owner, Manager, Member; Viewer denied).
    - External: Platform Operator or Product Admin.
    Buyer-side actors cannot create draft offers (403 Forbidden).
    Competitors receive 404 Not Found.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Create draft from revision request",
        description=(
            "Create a DRAFT OfferVersion from an OPEN RevisionRequest. "
            "Copies commercial semantics, specifications, and cost components from base version. "
            "Requires expected_version for optimistic concurrency control. "
            "Authorized for the Offer economic party representative (Supplier/Broker member or Operator). "
            "Buyer procurement actors cannot create draft offers. Competitors receive 404 Not Found."
        ),
        request=RevisionRequestDraftCreateSerializer,
        responses={
            201: OfferVersionResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - actor does not represent Offer economic party"),
            404: OpenApiResponse(description="RevisionRequest not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version, existing draft, or request not in OPEN status"),
        },
    )
    def post(self, request, request_id):
        rev_req = (
            RevisionRequest.objects.filter(pk=request_id)
            .select_related("offer", "offer__rfq")
            .first()
        )
        if not rev_req:
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rev_req.offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            rev_req.offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=rev_req.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if is_buyer_member and not (is_operator or is_offeror_member):
            return Response(
                {"detail": "Buyer procurement actors cannot create draft offers; only the Offer economic party may create a revised draft."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RevisionRequestDraftCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]

        try:
            draft_version = create_revised_draft_offer_version(
                actor=request.user,
                revision_request=rev_req,
                expected_version=expected_version,
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (RevisionRequestNotFoundError, OfferNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OfferVersionResponseSerializer(draft_version).data, status=status.HTTP_201_CREATED)


class RevisionRequestSubmitView(APIView):
    """
    Submit a revised OfferVersion and atomically resolve the OPEN RevisionRequest (T0811).

    Authorized for the Offer economic party representative:
    - Internal: Offering organization member (Owner, Manager, Member; Viewer denied).
    - External: Platform Operator or Product Admin.
    Buyer-side actors cannot submit revised offers (403 Forbidden).
    Competitors receive 404 Not Found.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Submit revised offer and resolve revision request",
        description=(
            "Submit a revised Draft OfferVersion and atomically transition the associated OPEN "
            "RevisionRequest to RESOLVED status. Requires expected_version for optimistic concurrency control. "
            "Authorized for the Offer economic party representative (Supplier/Broker member or Operator). "
            "Buyer procurement actors cannot submit revised offers. Competitors receive 404 Not Found."
        ),
        request=RevisionRequestSubmitSerializer,
        responses={
            200: OfferVersionResponseSerializer,
            400: OfferErrorResponseSerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            403: OpenApiResponse(description="Forbidden - actor does not represent Offer economic party"),
            404: OpenApiResponse(description="RevisionRequest or OfferVersion not found"),
            409: OpenApiResponse(description="Conflict - stale expected_version or request not in OPEN status"),
        },
    )
    def post(self, request, request_id):
        rev_req = (
            RevisionRequest.objects.filter(pk=request_id)
            .select_related("offer", "offer__rfq")
            .first()
        )
        if not rev_req:
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_operator = _is_operator_or_admin(request.user)
        is_buyer_member = OrganizationMembership.objects.filter(
            user=request.user,
            organization_id=rev_req.offer.rfq.organization_id,
            is_active=True,
            organization__is_active=True,
        ).exists()
        is_offeror_member = bool(
            rev_req.offer.offering_organization_id
            and OrganizationMembership.objects.filter(
                user=request.user,
                organization_id=rev_req.offer.offering_organization_id,
                is_active=True,
                organization__is_active=True,
            ).exists()
        )

        if not (is_operator or is_buyer_member or is_offeror_member):
            return Response(
                {"detail": f"RevisionRequest '{request_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if is_buyer_member and not (is_operator or is_offeror_member):
            return Response(
                {"detail": "Buyer procurement actors cannot submit revised offers; only the Offer economic party may submit."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RevisionRequestSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        expected_version = serializer.validated_data["expected_version"]
        draft_version_id = serializer.validated_data.get("draft_version_id")

        try:
            submitted_version, resolved_req = submit_revised_offer_version(
                actor=request.user,
                revision_request=rev_req,
                expected_version=expected_version,
                draft_version=draft_version_id,
            )
        except OfferPermissionDeniedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (RevisionRequestNotFoundError, OfferNotFoundError, OfferVersionNotFoundError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except (StaleVersionError, OfferConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (InvalidVersionError, OfferValidationError, OfferStateError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OfferVersionResponseSerializer(submitted_version).data, status=status.HTTP_200_OK)




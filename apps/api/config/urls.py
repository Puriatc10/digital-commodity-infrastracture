"""API routes; future Django apps can mount their URLs under /api/."""

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from offers.api.views import (
    AwardAllocationCreateView,
    AwardAllocationDetailView,
    AwardDetailView,
    AwardFinalizeView,
    DecisionRunDetailView,
    OfferVersionSubmitActionView,
    RFQAwardDetailView,
    RFQComparisonView,
    RFQDecisionRunCreateView,
    RevisionRequestCancelView,
    RevisionRequestCreateDraftView,
    RevisionRequestDeclineView,
    RevisionRequestDetailView,
    RevisionRequestSubmitView,
)
from deals.api.views import DealMaterializeActionView
from .views import health

urlpatterns = [
    path("api/health", health, name="health"),
    path("api/auth/", include("identity.urls")),
    path("api/organizations/", include("organizations.urls")),
    path("api/commodities/", include("commodities.urls")),
    path("api/commodity-schemas/", include("commodities.urls_schemas")),
    path("api/trade-hub/", include("trade_hub.urls")),
    path("api/opportunities/", include("opportunities.urls")),
    path("api/geography/", include("geography.urls")),
    path("api/matching/", include("matching.urls")),
    path("api/offers/", include("offers.urls")),
    path("api/offer-versions/<uuid:version_id>/submit/", OfferVersionSubmitActionView.as_view(), name="offer-version-submit-direct"),
    path("api/rfqs/<uuid:rfq_id>/comparison/", RFQComparisonView.as_view(), name="rfq-comparison-direct"),
    path("api/rfqs/<uuid:rfq_id>/decision-runs/", RFQDecisionRunCreateView.as_view(), name="rfq-decision-runs-direct"),
    path("api/decision-runs/<uuid:run_id>/", DecisionRunDetailView.as_view(), name="decision-run-detail-direct"),
    path("api/revision-requests/<uuid:request_id>/decline/", RevisionRequestDeclineView.as_view(), name="revision-request-decline-direct"),
    path("api/revision-requests/<uuid:request_id>/cancel/", RevisionRequestCancelView.as_view(), name="revision-request-cancel-direct"),
    path("api/revision-requests/<uuid:request_id>/", RevisionRequestDetailView.as_view(), name="revision-request-detail-direct"),
    path("api/revision-requests/<uuid:request_id>/draft/", RevisionRequestCreateDraftView.as_view(), name="revision-request-draft-direct"),
    path("api/revision-requests/<uuid:request_id>/submit/", RevisionRequestSubmitView.as_view(), name="revision-request-submit-direct"),
    path("api/rfqs/<uuid:rfq_id>/awards/", RFQAwardDetailView.as_view(), name="rfq-awards-direct"),
    path("api/rfqs/<uuid:rfq_id>/award/", RFQAwardDetailView.as_view(), name="rfq-award-direct"),
    path("api/awards/<uuid:award_id>/", AwardDetailView.as_view(), name="award-detail-direct"),
    path("api/awards/<uuid:award_id>/allocations/", AwardAllocationCreateView.as_view(), name="award-allocations-direct"),
    path("api/award-allocations/<uuid:allocation_id>/", AwardAllocationDetailView.as_view(), name="award-allocation-detail-direct"),
    path("api/awards/allocations/<uuid:allocation_id>/", AwardAllocationDetailView.as_view(), name="award-allocation-detail-alias-direct"),
    path("api/awards/<uuid:award_id>/finalize/", AwardFinalizeView.as_view(), name="award-finalize-direct"),
    path("api/awards/<uuid:award_id>/materialize-deals/", DealMaterializeActionView.as_view(), name="award-materialize-deals-direct"),
    path("api/deals/", include("deals.urls")),
    path("api/execution/", include("execution.urls")),


    path("", include("documents.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

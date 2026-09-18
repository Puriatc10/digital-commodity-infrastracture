"""API routes; future Django apps can mount their URLs under /api/."""

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from offers.api.views import (
    DecisionRunDetailView,
    OfferVersionSubmitActionView,
    RFQComparisonView,
    RFQDecisionRunCreateView,
    RevisionRequestCancelView,
    RevisionRequestDeclineView,
    RevisionRequestDetailView,
)
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

    path("", include("documents.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

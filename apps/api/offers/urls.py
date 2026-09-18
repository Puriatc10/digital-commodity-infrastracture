from django.urls import path

from offers.api.views import (
    DecisionRunDetailView,
    OfferDetailView,
    OfferVersionSubmitActionView,
    OperatorExternalOfferSubmissionActionView,
    RFQComparisonView,
    RFQDecisionRunCreateView,
    RFQOffersListView,
)


app_name = "offers"

urlpatterns = [
    path(
        "operator-submission/",
        OperatorExternalOfferSubmissionActionView.as_view(),
        name="operator-external-offer-submission",
    ),
    path(
        "rfqs/<uuid:rfq_id>/operator-submission/",
        OperatorExternalOfferSubmissionActionView.as_view(),
        name="operator-external-offer-submission-rfq",
    ),
    path(
        "rfqs/<uuid:rfq_id>/comparison/",
        RFQComparisonView.as_view(),
        name="rfq-comparison",
    ),
    path(
        "rfqs/<uuid:rfq_id>/",
        RFQOffersListView.as_view(),
        name="rfq-offers-list",
    ),
    path(
        "<uuid:offer_id>/",
        OfferDetailView.as_view(),
        name="offer-detail",
    ),
    path(
        "offer-versions/<uuid:version_id>/submit/",
        OfferVersionSubmitActionView.as_view(),
        name="offer-version-submit",
    ),
    path(
        "rfqs/<uuid:rfq_id>/decision-runs/",
        RFQDecisionRunCreateView.as_view(),
        name="rfq-decision-runs",
    ),
    path(
        "decision-runs/<uuid:run_id>/",
        DecisionRunDetailView.as_view(),
        name="decision-run-detail",
    ),
]


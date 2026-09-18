from django.urls import path

from matching.api.views import (
    MatchingRunCandidateListView,
    MatchingRunDetailView,
    RFQMatchingRunListCreateView,
)

app_name = "matching"

urlpatterns = [
    path("rfqs/<uuid:rfq_id>/runs/", RFQMatchingRunListCreateView.as_view(), name="matching-rfq-runs"),
    path("runs/<uuid:run_id>/", MatchingRunDetailView.as_view(), name="matching-run-detail"),
    path("runs/<uuid:run_id>/candidates/", MatchingRunCandidateListView.as_view(), name="matching-run-candidates"),
]

from django.urls import path

from deals.api.views import (
    DealDetailView,
    DealListView,
    DealPartiesSnapshotView,
    DealTermsSnapshotView,
)

app_name = "deals"

urlpatterns = [
    path(
        "",
        DealListView.as_view(),
        name="deal-list",
    ),
    path(
        "<uuid:deal_id>/",
        DealDetailView.as_view(),
        name="deal-detail",
    ),
    path(
        "<uuid:deal_id>/terms/",
        DealTermsSnapshotView.as_view(),
        name="deal-terms-snapshot",
    ),
    path(
        "<uuid:deal_id>/parties/",
        DealPartiesSnapshotView.as_view(),
        name="deal-parties-snapshot",
    ),
]

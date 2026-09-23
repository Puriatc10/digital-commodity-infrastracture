from django.urls import path

from deals.api.views import (
    DealAttributionDetailView,
    DealAttributionResolveView,
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
    path(
        "<uuid:deal_id>/attribution/",
        DealAttributionDetailView.as_view(),
        name="deal-attribution",
    ),
    path(
        "<uuid:deal_id>/attribution/resolve/",
        DealAttributionResolveView.as_view(),
        name="deal-attribution-resolve",
    ),
]


from django.urls import path

from deals.api.views import (
    DealAttributionDetailView,
    DealAttributionResolveView,
    DealDetailView,
    DealListView,
    DealPartiesSnapshotView,
    DealTermsSnapshotView,
)
from execution.api.views import (
    DealExecutionCreateOrGetView,
    DealExecutionInspectionView,
    DealExecutionLogisticsView,
    DealMilestoneCompleteActionView,
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
    path(
        "<uuid:deal_id>/execution/",
        DealExecutionCreateOrGetView.as_view(),
        name="deal-execution",
    ),
    path(
        "<uuid:deal_id>/execution/logistics/",
        DealExecutionLogisticsView.as_view(),
        name="deal-execution-logistics",
    ),
    path(
        "<uuid:deal_id>/execution/inspection/",
        DealExecutionInspectionView.as_view(),
        name="deal-execution-inspection",
    ),
    path(
        "<uuid:deal_id>/execution/milestones/<uuid:milestone_id>/complete/",
        DealMilestoneCompleteActionView.as_view(),
        name="deal-execution-milestone-complete",
    ),
]




from django.urls import path

from deals.api.views import DealDetailView, DealListView

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
]

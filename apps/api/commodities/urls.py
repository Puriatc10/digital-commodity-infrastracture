from django.urls import path
from .views import CommodityListView, ActiveCommoditySchemaView

urlpatterns = [
    path("", CommodityListView.as_view(), name="commodity-list"),
    path("<str:code>/schema/", ActiveCommoditySchemaView.as_view(), name="commodity-active-schema"),
]

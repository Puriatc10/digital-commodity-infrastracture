from django.urls import path
from .views import CommoditySchemaDetailView

urlpatterns = [
    path("<uuid:pk>/", CommoditySchemaDetailView.as_view(), name="commodity-schema-detail"),
]

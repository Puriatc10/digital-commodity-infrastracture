from django.urls import path

from geography.api.views import GeographicAreaDetailView, GeographicAreaListView

urlpatterns = [
    path("areas/", GeographicAreaListView.as_view(), name="geographic-area-list"),
    path("areas/<uuid:pk>/", GeographicAreaDetailView.as_view(), name="geographic-area-detail"),
]

"""API routes; future Django apps can mount their URLs under /api/."""

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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
    path("", include("documents.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

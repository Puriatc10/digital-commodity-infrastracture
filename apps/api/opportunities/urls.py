from django.urls import path
from rest_framework.routers import DefaultRouter

from opportunities.api.views import (
    ExternalCounterpartyViewSet,
    OpportunityContactAttemptDetailView,
    OpportunityContactAttemptListCreateView,
    OpportunityViewSet,
)

router = DefaultRouter()
router.register(
    r"external-counterparties",
    ExternalCounterpartyViewSet,
    basename="external-counterparty",
)
router.register(
    r"opportunities",
    OpportunityViewSet,
    basename="opportunity",
)

urlpatterns = [
    path(
        "opportunities/<str:opportunity_id>/contact-attempts/",
        OpportunityContactAttemptListCreateView.as_view(),
        name="opportunity-contact-attempts-list-create",
    ),
    path(
        "opportunities/<str:opportunity_id>/contact-attempts/<str:attempt_id>/",
        OpportunityContactAttemptDetailView.as_view(),
        name="opportunity-contact-attempts-detail",
    ),
    *router.urls,
]

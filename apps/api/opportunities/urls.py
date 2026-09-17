from django.urls import path
from rest_framework.routers import DefaultRouter

from opportunities.api.views import (
    ExternalCounterpartyViewSet,
    OpportunityContactAttemptDetailView,
    OpportunityContactAttemptListCreateView,
    OpportunityTaskCancelView,
    OpportunityTaskCompleteView,
    OpportunityTaskDetailView,
    OpportunityTaskListCreateView,
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
    path(
        "opportunities/<str:opportunity_id>/tasks/",
        OpportunityTaskListCreateView.as_view(),
        name="opportunity-tasks-list-create",
    ),
    path(
        "opportunities/<str:opportunity_id>/tasks/<str:task_id>/",
        OpportunityTaskDetailView.as_view(),
        name="opportunity-tasks-detail",
    ),
    path(
        "opportunities/<str:opportunity_id>/tasks/<str:task_id>/complete/",
        OpportunityTaskCompleteView.as_view(),
        name="opportunity-tasks-complete",
    ),
    path(
        "opportunities/<str:opportunity_id>/tasks/<str:task_id>/cancel/",
        OpportunityTaskCancelView.as_view(),
        name="opportunity-tasks-cancel",
    ),
    *router.urls,
]

from rest_framework.routers import DefaultRouter

from opportunities.api.views import ExternalCounterpartyViewSet, OpportunityViewSet

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

urlpatterns = router.urls

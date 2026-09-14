from rest_framework.routers import DefaultRouter

from opportunities.api.views import ExternalCounterpartyViewSet

router = DefaultRouter()
router.register(
    r"external-counterparties",
    ExternalCounterpartyViewSet,
    basename="external-counterparty",
)

urlpatterns = router.urls

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api.views import OrganizationViewSet

router = DefaultRouter()
router.register(r'', OrganizationViewSet, basename='organization')

urlpatterns = [
    path('<uuid:org_id>/verification/', include(('organizations.verification.urls', 'verification'), namespace='verification')),
    path('', include(router.urls)),
]

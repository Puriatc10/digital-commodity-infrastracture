from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api.views import OrganizationViewSet, DirectoryViewSet, ProfileViewSet

router = DefaultRouter()
router.register(r'directory', DirectoryViewSet, basename='directory')
router.register(r'profiles', ProfileViewSet, basename='profile')
router.register(r'', OrganizationViewSet, basename='organization')

from organizations.verification import api_views as verification_api_views

urlpatterns = [
    path('verification/cases/', verification_api_views.VerificationQueueListView.as_view(), name='verification-queue'),
    path('<uuid:org_id>/verification/', include(('organizations.verification.urls', 'verification'), namespace='verification')),
    path('', include(router.urls)),
]

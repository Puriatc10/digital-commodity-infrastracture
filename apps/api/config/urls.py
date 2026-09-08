"""API routes; future Django apps can mount their URLs under /api/."""

from django.urls import path

from .views import health

urlpatterns = [
    path("api/health", health, name="health"),
]

"""Production settings require explicit environment configuration and HTTPS."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS in production.")

SECURE_SSL_REDIRECT = True
CSRF_COOKIE_SECURE = True

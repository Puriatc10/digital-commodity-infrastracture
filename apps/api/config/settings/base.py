"""Shared settings; runtime values come from the environment."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env()

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
DEMO_PERSONA_SWITCHER_ENABLED = env.bool("DEMO_PERSONA_SWITCHER_ENABLED", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "identity",
    "organizations",
    "organizations.verification",
    "commodities",
    "documents",
    "trade_hub",
    "opportunities",
    "matching",
    "geography",
]

# drf-spectacular renders the Swagger UI from its packaged template.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
    }
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env.str("POSTGRES_HOST", default="127.0.0.1"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "NAME": env.str("POSTGRES_DB"),
        "USER": env.str("POSTGRES_USER"),
        "PASSWORD": env.str("POSTGRES_PASSWORD"),
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Commodity Platform API",
    "DESCRIPTION": "Backend OpenAPI for the commodity procurement platform",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "VerificationStatusEnum": "organizations.verification.models.VerificationStatus",
        "RFQInvitationStatusEnum": "trade_hub.models.RFQInvitationStatus",
        "RFQStatusEnum": "trade_hub.models.RFQStatus",
        "RFQVisibilityEnum": "trade_hub.models.RFQVisibility",
        "SupplyListingStatusEnum": "trade_hub.models.SupplyListingStatus",
        "OpportunityDirectionEnum": "opportunities.models.OpportunityDirection",
        "OpportunityStatusEnum": "opportunities.models.OpportunityStatus",
        "ContactAttemptTypeEnum": "opportunities.models.ContactAttemptType",
        "DocumentTypeEnum": "documents.models.DocumentType",
        "AreaTypeEnum": "geography.models.AreaType",
        "GeographyConstraintModeEnum": "trade_hub.models.GeographyConstraintMode",
    },
}

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "identity.User"

# MinIO / Object Storage Settings
MINIO_ENDPOINT = env.str("MINIO_ENDPOINT", default="127.0.0.1:9000")
MINIO_ACCESS_KEY = env.str("MINIO_ACCESS_KEY", default="minioadmin")
MINIO_SECRET_KEY = env.str("MINIO_SECRET_KEY", default="minioadmin")
MINIO_USE_SSL = env.bool("MINIO_USE_SSL", default=False)
MINIO_BUCKET_NAME = env.str("MINIO_BUCKET_NAME", default="verification-documents")

"""Base settings shared by every environment.

Secrets and deployment-specific values come from environment variables only.
See .env.example at the repository root for the full list.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env()

# Load the repository-level .env file when present (local development).
# In Docker and production the variables are provided by the environment.
_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

# --- Applications -----------------------------------------------------------
#
# IMPORTANT (Slice 0): django.contrib.auth, sessions and admin are deliberately
# NOT installed yet. Slice 1 installs them together with the custom User model
# so that AUTH_USER_MODEL is set before any auth-related migration exists.
# See docs/DECISIONS.md, entry D-003.

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.rbac",
    "apps.organisation",
    "apps.approvals",
    "apps.audit",
    "apps.dashboard",
    # Phase Two and later apps are intentionally not created yet.
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database ---------------------------------------------------------------
# PostgreSQL only. No default: the project refuses to start without it.

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Internationalisation ---------------------------------------------------

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_I18N = True
USE_TZ = True

# --- Static files (the React build is served by the web server, not Django) -

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Security defaults ------------------------------------------------------

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# The React app reads the CSRF token from this cookie and sends it back in a
# header. The session cookie (added in Slice 1) will be HttpOnly.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# --- Django REST Framework --------------------------------------------------

REST_FRAMEWORK = {
    # Secure by default: every view denies access unless it explicitly declares
    # a permission class. Slice 2 replaces this with the central RBAC engine.
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.permissions.DenyByDefault"],
    # Authentication classes arrive with Slice 1 (session authentication).
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
    # JSON only: no browsable API in any environment.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.api.StandardPagination",
    "PAGE_SIZE": 25,
}

# --- Logging ----------------------------------------------------------------
# Never log request bodies, passwords, tokens or child information.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},
}

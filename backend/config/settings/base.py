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
# Slice 1 installs django.contrib.auth and sessions together with the custom
# User model (AUTH_USER_MODEL = accounts.User), as planned in docs/DECISIONS.md
# D-003. The Django admin site is intentionally NOT installed: all
# administration happens through TCOS's own permission-checked interface.

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionPolicyMiddleware",
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
# header. The session cookie is HttpOnly and never readable by JavaScript.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

# --- Authentication ---------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

# Argon2id first; PBKDF2 stays listed only so old hashes can still be verified
# and are upgraded to Argon2 on the next successful login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("username", "email", "full_name")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Sessions ---------------------------------------------------------------
# Server-side sessions in the database so an administrator or the user can end
# them immediately. The cookie holds only a random key.

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# Idle timeout: the session expires after this many seconds without a request.
SESSION_COOKIE_AGE = env.int("TCOS_SESSION_IDLE_SECONDS", default=30 * 60)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Absolute timeout: a session ends this long after sign-in however active it is.
TCOS_SESSION_ABSOLUTE_SECONDS = env.int("TCOS_SESSION_ABSOLUTE_SECONDS", default=12 * 60 * 60)

# --- Login protection -------------------------------------------------------
# After this many failed attempts for one username (whether or not the account
# exists) sign-in is blocked until old failures leave the window.
TCOS_LOGIN_MAX_FAILURES = env.int("TCOS_LOGIN_MAX_FAILURES", default=5)
TCOS_LOGIN_WINDOW_MINUTES = env.int("TCOS_LOGIN_WINDOW_MINUTES", default=15)
# Failed attempts from one IP address across all usernames.
TCOS_LOGIN_IP_MAX_FAILURES = env.int("TCOS_LOGIN_IP_MAX_FAILURES", default=30)
# Number of trusted reverse proxies in front of Django. 0 = use the connection
# address. Only set above 0 when X-Forwarded-For is added by YOUR proxy.
TCOS_TRUSTED_PROXY_COUNT = env.int("TCOS_TRUSTED_PROXY_COUNT", default=0)

# --- Django REST Framework --------------------------------------------------

REST_FRAMEWORK = {
    # Secure by default: every view denies access unless it explicitly declares
    # a permission class. Slice 2 replaces this with the central RBAC engine.
    "DEFAULT_PERMISSION_CLASSES": ["apps.rbac.permissions.RBACPermission"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.TcosSessionAuthentication"],
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

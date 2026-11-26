"""Test settings: the real dev settings plus a throwaway app and routes."""

from config.settings.dev import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "tests.rbac_testapp"]  # noqa: F405
ROOT_URLCONF = "tests.urls_test"
TCOS_EMAIL_ASYNC = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# A throwaway key that protects nothing: tests only.
TCOS_ENCRYPTION_KEY = "dGVzdC1vbmx5LWtleS1ub3QtYS1zZWNyZXQtMDEyMzQ"
import tempfile  # noqa: E402

TCOS_PRIVATE_STORAGE_ROOT = tempfile.mkdtemp(prefix="tcos-test-files-")

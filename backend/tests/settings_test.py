"""Test settings: the real dev settings plus a throwaway app and routes."""

from config.settings.dev import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "tests.rbac_testapp"]  # noqa: F405
ROOT_URLCONF = "tests.urls_test"

"""Production settings must fail closed and pass Django's deployment checks.

These tests run Django in a subprocess with production settings so the
development configuration used by the rest of the test suite cannot mask a
problem.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run(args, env_overrides, drop=()):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_overrides)
    return subprocess.run(  # noqa: S603
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _prod_env():
    return {
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_ALLOWED_HOSTS": "tcos.example.org",
        "DATABASE_URL": "postgres://user:pass@localhost:5432/db",
    }


def test_prod_refuses_to_start_without_secret_key():
    env = _prod_env()
    env["DJANGO_SECRET_KEY"] = ""
    result = _run(["manage.py", "check"], env)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_prod_refuses_to_start_without_allowed_hosts():
    env = _prod_env()
    env["DJANGO_ALLOWED_HOSTS"] = ""
    result = _run(["manage.py", "check"], env)
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_prod_has_debug_off_and_secure_cookies():
    code = (
        "import django; django.setup();"
        "from django.conf import settings as s;"
        "assert s.DEBUG is False;"
        "assert s.SESSION_COOKIE_SECURE is True;"
        "assert s.CSRF_COOKIE_SECURE is True;"
        "assert s.SECURE_SSL_REDIRECT is True;"
        "assert s.SECURE_HSTS_SECONDS >= 31536000;"
        "print('ok')"
    )
    result = _run(["-c", code], _prod_env())
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_prod_passes_django_deploy_check_with_no_errors():
    result = _run(["manage.py", "check", "--deploy", "--fail-level", "ERROR"], _prod_env())
    assert result.returncode == 0, result.stdout + result.stderr

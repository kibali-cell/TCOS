import itertools

import pytest
from rest_framework.test import APIClient

from apps.accounts.services import create_user

PASSWORD = "correct-horse-battery-9"
FAST_HASHER = "django.contrib.auth.hashers.MD5PasswordHasher"  # tests only: speed


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """Argon2 is deliberately slow; tests use a fast hasher unless they opt out."""
    settings.PASSWORD_HASHERS = [FAST_HASHER]


@pytest.fixture
def make_user(db):
    counter = itertools.count(1)

    def _make(username=None, password=PASSWORD, **kwargs):
        number = next(counter)
        username = username or f"user{number}"
        return create_user(
            username=username,
            email=kwargs.pop("email", f"{username}@example.org"),
            full_name=kwargs.pop("full_name", f"Test User {number}"),
            password=password,
            **kwargs,
        )

    return _make


@pytest.fixture
def new_client():
    """A fresh browser: its own cookies, and CSRF checks switched ON like a real browser."""

    def _new():
        return APIClient(enforce_csrf_checks=True)

    return _new


def csrf_token(client) -> str:
    if "csrftoken" not in client.cookies:
        client.get("/api/v1/csrf/")
    return client.cookies["csrftoken"].value


def post(client, url, data=None, **extra):
    return client.post(url, data or {}, format="json", HTTP_X_CSRFTOKEN=csrf_token(client), **extra)


def delete(client, url, **extra):
    return client.delete(url, HTTP_X_CSRFTOKEN=csrf_token(client), **extra)


def put(client, url, data=None, **extra):
    return client.put(url, data or {}, format="json", HTTP_X_CSRFTOKEN=csrf_token(client), **extra)


def patch(client, url, data=None, **extra):
    return client.patch(
        url, data or {}, format="json", HTTP_X_CSRFTOKEN=csrf_token(client), **extra
    )


def sign_in(client, username, password=PASSWORD, **extra):
    return post(
        client, "/api/v1/auth/login/", {"username": username, "password": password}, **extra
    )


@pytest.fixture
def signed_in(new_client, make_user):
    """A user with one signed-in browser."""

    def _signed_in(username=None, **user_kwargs):
        user = make_user(username, **user_kwargs)
        client = new_client()
        response = sign_in(client, user.username)
        assert response.status_code == 200, response.content
        return user, client

    return _signed_in


# --- RBAC helpers --------------------------------------------------------------------


@pytest.fixture
def departments(db):
    from apps.organisation.models import Department

    return {
        "A": Department.objects.create(code="DEPT-A", name="Department A"),
        "B": Department.objects.create(code="DEPT-B", name="Department B"),
    }


def give_role(user, code, department=None, **extra):
    """Assign a seeded role directly (bypasses the API on purpose: test setup only)."""
    from apps.rbac.models import Role, UserRole

    return UserRole.objects.create(
        user=user, role=Role.objects.get(code=code), department=department, **extra
    )


@pytest.fixture
def staff(new_client, make_user):
    """A signed-in user holding the given seeded role(s): staff("FINANCE_OFFICER", ...)."""

    def _staff(*codes, department=None, username=None, role_department=None, **user_kwargs):
        user = make_user(username, department=department, **user_kwargs)
        for code in codes:
            give_role(user, code, department=role_department)
        client = new_client()
        response = sign_in(client, user.username)
        assert response.status_code == 200, response.content
        return user, client

    return _staff

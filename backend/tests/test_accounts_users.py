"""Account creation, validation and the first-administrator command."""

from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.accounts.services import create_user

from .conftest import PASSWORD

ARGON2 = "django.contrib.auth.hashers.Argon2PasswordHasher"


def test_create_user_normalises_names_and_hashes_password(make_user):
    user = make_user("  Alice.Smith ", email=" Alice@Example.ORG ")

    assert user.username == "alice.smith"
    assert user.email == "alice@example.org"
    assert user.password != PASSWORD
    assert PASSWORD not in user.password
    assert user.check_password(PASSWORD)
    assert user.status == User.Status.ACTIVE
    assert user.password_changed_at is not None
    assert str(user.id)  # UUID primary key


def test_passwords_are_stored_with_argon2id(settings, db):
    settings.PASSWORD_HASHERS = [ARGON2]
    user = create_user(
        username="argonuser", email="a@example.org", full_name="Argon User", password=PASSWORD
    )
    assert user.password.startswith("argon2$argon2id$")


@pytest.mark.parametrize(
    "password",
    [
        "short1",  # too short
        "password1234",  # common
        "123456789012345",  # entirely numeric
        "alicesmith2026",  # similar to the username
    ],
)
def test_weak_passwords_are_rejected(db, password):
    with pytest.raises(ValidationError):
        create_user(
            username="alicesmith", email="alice@example.org", full_name="Alice", password=password
        )
    assert not User.objects.exists()


def test_username_uniqueness_is_case_insensitive(make_user):
    make_user("Alice")
    with pytest.raises(ValidationError):
        make_user("ALICE", email="other@example.org")


def test_email_uniqueness_is_case_insensitive(make_user):
    make_user("first", email="same@example.org")
    with pytest.raises(ValidationError):
        make_user("second", email="SAME@example.org")


@pytest.mark.parametrize("username", ["ab", "bad name", "bad/name", "-leading", "x" * 151])
def test_invalid_usernames_are_rejected(make_user, username):
    with pytest.raises(ValidationError):
        make_user(username)


@pytest.mark.parametrize("phone", ["abc", "12", "+255 700 000 000 000 000"])
def test_invalid_phone_numbers_are_rejected(make_user, phone):
    with pytest.raises(ValidationError):
        make_user("phoneuser", phone=phone)


def test_valid_phone_numbers_are_accepted(make_user):
    assert make_user("phoneuser", phone="+255 700 000 000").phone == "+255 700 000 000"


def test_database_rejects_non_lowercase_username_even_if_code_is_bypassed(make_user):
    user = make_user("lowercase")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(username="UPPERCASE")


def test_database_rejects_invalid_status(make_user):
    user = make_user("statususer")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status="WHATEVER")


@pytest.mark.parametrize(
    ("status", "active"),
    [("ACTIVE", True), ("INACTIVE", False), ("LOCKED", False), ("PENDING", False)],
)
def test_is_active_follows_status(make_user, status, active):
    assert make_user("statuscheck", status=status).is_active is active


# --- create_initial_admin ---------------------------------------------------


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("TCOS_ADMIN_USERNAME", "First.Admin")
    monkeypatch.setenv("TCOS_ADMIN_EMAIL", "Admin@Example.org")
    monkeypatch.setenv("TCOS_ADMIN_FULL_NAME", "First Administrator")
    monkeypatch.setenv("TCOS_ADMIN_PASSWORD", PASSWORD)


def test_create_initial_admin_from_environment(db, admin_env):
    out = StringIO()
    call_command("create_initial_admin", stdout=out)

    user = User.objects.get(username="first.admin")
    assert user.is_superuser and user.is_active
    assert user.check_password(PASSWORD)
    assert PASSWORD not in out.getvalue()  # the password is never printed


def test_create_initial_admin_refuses_when_users_exist(db, admin_env, make_user):
    make_user("existing")
    with pytest.raises(CommandError, match="already exist"):
        call_command("create_initial_admin")
    assert User.objects.count() == 1


def test_create_initial_admin_force_allows_another(db, admin_env, make_user):
    make_user("existing")
    call_command("create_initial_admin", force=True)
    assert User.objects.count() == 2


def test_create_initial_admin_enforces_password_policy(db, admin_env, monkeypatch):
    monkeypatch.setenv("TCOS_ADMIN_PASSWORD", "password1234")
    with pytest.raises(CommandError, match="Could not create"):
        call_command("create_initial_admin")
    assert not User.objects.exists()


def test_create_initial_admin_has_no_default_credentials(db, monkeypatch):
    for name in ("USERNAME", "EMAIL", "FULL_NAME", "PASSWORD"):
        monkeypatch.delenv(f"TCOS_ADMIN_{name}", raising=False)
    with pytest.raises(CommandError):
        call_command("create_initial_admin")
    assert not User.objects.exists()

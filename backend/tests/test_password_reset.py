"""Password reset: single-use, time-limited, no enumeration, ends all sessions."""

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import PasswordResetToken, User, UserSession
from apps.audit import events
from apps.audit.models import AuditEvent
from tests.conftest import PASSWORD, post, sign_in

FORGOT = "/api/v1/auth/password/forgot/"
RESET = "/api/v1/auth/password/reset/"
NEW_PASSWORD = "a-brand-new-passphrase-42"


def ask(client, identifier, capture):
    with capture(execute=True):
        return post(client, FORGOT, {"identifier": identifier})


def token_from(mailoutbox):
    match = re.search(r"#token=([\w-]+)", mailoutbox[-1].body)
    assert match, mailoutbox[-1].body
    return match.group(1)


def test_known_and_unknown_accounts_get_identical_answers(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    make_user("amina", email="amina@example.org")
    real = ask(new_client(), "amina", django_capture_on_commit_callbacks)
    fake = ask(new_client(), "nobody-here", django_capture_on_commit_callbacks)
    assert (real.status_code, real.json()) == (fake.status_code, fake.json())
    assert real.status_code == 202
    assert len(mailoutbox) == 1  # only the real one is mailed
    assert mailoutbox[0].to == ["amina@example.org"]


def test_e_mail_can_be_used_as_the_identifier_and_inactive_accounts_get_nothing(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    make_user("amina", email="amina@example.org")
    make_user("gone", email="gone@example.org", status="INACTIVE")
    ask(new_client(), "Amina@Example.org", django_capture_on_commit_callbacks)
    ask(new_client(), "gone", django_capture_on_commit_callbacks)
    assert len(mailoutbox) == 1


def test_token_is_stored_hashed_and_never_logged(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user("amina")
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    raw = token_from(mailoutbox)
    row = PasswordResetToken.objects.get(user=user)
    assert raw not in row.token_hash and len(row.token_hash) == 64
    everything = str(list(AuditEvent.objects.values_list("changes", "metadata", "object_id")))
    assert raw not in everything


def test_reset_works_once_then_the_link_is_dead(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user("amina")
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    raw = token_from(mailoutbox)
    browser = new_client()
    assert post(browser, RESET, {"token": raw, "new_password": NEW_PASSWORD}).status_code == 200
    assert sign_in(new_client(), "amina", NEW_PASSWORD).status_code == 200
    assert sign_in(new_client(), "amina", PASSWORD).status_code == 401
    again = post(new_client(), RESET, {"token": raw, "new_password": "another-passphrase-77"})
    assert again.status_code == 400
    assert AuditEvent.objects.filter(event_type=events.PASSWORD_RESET_COMPLETED).count() == 1
    assert AuditEvent.objects.filter(event_type=events.PASSWORD_RESET_FAILED).exists()
    assert not User.objects.get(pk=user.pk).must_change_password


def test_an_expired_token_is_refused(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user("amina")
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    raw = token_from(mailoutbox)
    PasswordResetToken.objects.filter(user=user).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    response = post(new_client(), RESET, {"token": raw, "new_password": NEW_PASSWORD})
    assert response.status_code == 400
    assert sign_in(new_client(), "amina", PASSWORD).status_code == 200  # password unchanged


def test_garbage_and_wrong_tokens_give_the_same_answer_as_expired(new_client, make_user):
    make_user("amina")
    a = post(new_client(), RESET, {"token": "not-a-token", "new_password": NEW_PASSWORD})
    b = post(new_client(), RESET, {"token": "x" * 80, "new_password": NEW_PASSWORD})
    assert a.status_code == b.status_code == 400
    assert a.json() == b.json()


def test_a_weak_new_password_is_refused_and_the_link_stays_usable(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    make_user("amina")
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    raw = token_from(mailoutbox)
    weak = post(new_client(), RESET, {"token": raw, "new_password": "short"})
    assert weak.status_code == 400
    assert (
        post(new_client(), RESET, {"token": raw, "new_password": NEW_PASSWORD}).status_code == 200
    )


def test_reset_ends_every_session_and_a_new_request_voids_older_links(
    make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user("amina")
    phone, laptop = new_client(), new_client()
    sign_in(phone, "amina")
    sign_in(laptop, "amina")
    assert UserSession.objects.filter(user=user, ended_at__isnull=True).count() == 2
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    first = token_from(mailoutbox)
    ask(new_client(), "amina", django_capture_on_commit_callbacks)
    second = token_from(mailoutbox)
    assert (
        post(new_client(), RESET, {"token": first, "new_password": NEW_PASSWORD}).status_code == 400
    )
    assert (
        post(new_client(), RESET, {"token": second, "new_password": NEW_PASSWORD}).status_code
        == 200
    )
    assert not UserSession.objects.filter(user=user, ended_at__isnull=True).exists()
    assert phone.get("/api/v1/auth/me/").status_code in (401, 403)
    assert laptop.get("/api/v1/auth/me/").status_code in (401, 403)


def test_requests_are_rate_limited_without_revealing_anything(
    make_user, new_client, mailoutbox, settings, django_capture_on_commit_callbacks
):
    settings.TCOS_RESET_MAX_PER_ACCOUNT_HOUR = 2
    make_user("amina")
    answers = [
        ask(new_client(), "amina", django_capture_on_commit_callbacks).json() for _ in range(5)
    ]
    assert len({str(a) for a in answers}) == 1
    assert len(mailoutbox) == 2
    # An unknown name is counted the same way, so the limit cannot be used to find accounts.
    for _ in range(5):
        assert ask(new_client(), "ghost", django_capture_on_commit_callbacks).status_code == 202


def test_per_address_limit_applies_across_names(
    make_user, new_client, mailoutbox, settings, django_capture_on_commit_callbacks
):
    settings.TCOS_RESET_MAX_PER_IP_HOUR = 2
    for name in ("one", "two", "three"):
        make_user(name)
    for name in ("one", "two", "three"):
        ask(new_client(), name, django_capture_on_commit_callbacks)
    assert len(mailoutbox) == 2


@pytest.mark.parametrize("path", [FORGOT, RESET])
def test_reset_endpoints_need_csrf_like_any_form(path, new_client):
    assert (
        new_client().post(path, {"identifier": "x", "token": "x"}, format="json").status_code == 403
    )

"""Sign-in, sign-out, CSRF, lockout and session timeouts."""

import time
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.accounts.models import LoginAttempt, User, UserSession
from apps.accounts.permissions import IsSignedIn
from apps.accounts.services import list_active_sessions

from .conftest import PASSWORD, post, sign_in

CHROME_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
WRONG = "not-the-password-123"


# --- Sign-in ----------------------------------------------------------------


def test_sign_in_success(new_client, make_user):
    user = make_user("alice", full_name="Alice Mwangi")
    client = new_client()

    response = sign_in(client, "Alice", HTTP_USER_AGENT=CHROME_WINDOWS)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["full_name"] == "Alice Mwangi"
    text = response.content.decode().lower()
    assert PASSWORD not in text and "argon" not in text and "session_key" not in text
    assert body["session"]["idle_expires_at"] and body["session"]["absolute_expires_at"]

    cookie = response.cookies["sessionid"]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Lax"

    user.refresh_from_db()
    assert user.last_login is not None
    attempt = LoginAttempt.objects.get()
    assert attempt.success and attempt.user == user and attempt.failure_reason == ""
    session = UserSession.objects.get()
    assert session.user == user and session.device_label == "Chrome on Windows"


def test_me_requires_sign_in():
    response = APIClient().get("/api/v1/auth/me/")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Session"
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_returns_profile_without_secrets(signed_in):
    user, client = signed_in("alice")
    response = client.get("/api/v1/auth/me/")
    assert response.status_code == 200
    text = response.content.decode()
    assert response.json()["user"]["id"] == str(user.id)
    for secret in (PASSWORD, "argon", "lockout", "is_superuser", "session_key", '"password"'):
        assert secret not in text


def test_failed_sign_ins_are_indistinguishable(new_client, make_user):
    make_user("alice")
    make_user("dormant", status=User.Status.INACTIVE)

    responses = [
        sign_in(new_client(), "alice", WRONG),  # wrong password
        sign_in(new_client(), "nobody", WRONG),  # unknown user
        sign_in(new_client(), "dormant", PASSWORD),  # inactive, correct password
    ]

    assert {r.status_code for r in responses} == {401}
    assert len({r.content for r in responses}) == 1  # identical body
    assert responses[0].json()["error"]["code"] == "invalid_credentials"
    assert all("sessionid" not in r.cookies for r in responses)

    reasons = list(
        LoginAttempt.objects.order_by("attempted_at").values_list("failure_reason", flat=True)
    )
    assert reasons == ["BAD_CREDENTIALS", "BAD_CREDENTIALS", "ACCOUNT_NOT_ACTIVE"]
    assert not LoginAttempt.objects.filter(success=True).exists()
    assert not UserSession.objects.exists()


def test_failed_attempts_record_ip_and_user_agent(new_client, make_user):
    make_user("alice")
    sign_in(new_client(), "alice", WRONG, HTTP_USER_AGENT="TestAgent/1.0", REMOTE_ADDR="10.1.2.3")
    attempt = LoginAttempt.objects.get()
    assert attempt.ip_address == "10.1.2.3" and attempt.user_agent == "TestAgent/1.0"


def test_missing_fields_are_validation_errors(new_client):
    response = post(new_client(), "/api/v1/auth/login/", {"username": "alice"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


# --- CSRF -------------------------------------------------------------------


def test_sign_in_without_csrf_token_is_refused(make_user):
    make_user("alice")
    client = APIClient(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/auth/login/", {"username": "alice", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert not UserSession.objects.exists()
    assert not LoginAttempt.objects.exists()


def test_sign_in_with_wrong_csrf_token_is_refused(make_user):
    make_user("alice")
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/csrf/")
    response = client.post(
        "/api/v1/auth/login/",
        {"username": "alice", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN="not-the-real-token",
    )
    assert response.status_code == 403


def test_signed_in_requests_also_require_csrf(signed_in):
    _, client = signed_in("alice")
    response = client.post("/api/v1/auth/logout/", format="json")  # no token header
    assert response.status_code == 403
    assert client.get("/api/v1/auth/me/").status_code == 200  # still signed in


# --- Sign-out ----------------------------------------------------------------


def test_sign_out_ends_the_session_everywhere(new_client, signed_in):
    user, client = signed_in("alice")
    stolen_cookie = client.cookies["sessionid"].value
    key = UserSession.objects.get().session_key

    response = post(client, "/api/v1/auth/logout/")

    assert response.status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert not Session.objects.filter(session_key=key).exists()
    ended = UserSession.objects.get()
    assert ended.ended_at is not None and ended.ended_reason == "LOGOUT"

    replay = new_client()
    replay.cookies["sessionid"] = stolen_cookie  # an attacker replaying the old cookie
    assert replay.get("/api/v1/auth/me/").status_code == 401


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/api/v1/auth/me/"),
        ("post", "/api/v1/auth/logout/"),
        ("get", "/api/v1/auth/sessions/"),
        ("post", "/api/v1/auth/sessions/end-others/"),
        ("delete", "/api/v1/auth/sessions/6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11/"),
        ("post", "/api/v1/auth/password/change/"),
    ],
)
def test_protected_endpoints_reject_anonymous_users(method, url):
    response = getattr(APIClient(), method)(url)
    assert response.status_code == 401


def test_signing_in_again_replaces_the_previous_session(new_client, make_user):
    make_user("alice")
    client = new_client()
    sign_in(client, "alice")
    first_cookie = client.cookies["sessionid"].value

    sign_in(client, "alice")

    assert client.cookies["sessionid"].value != first_cookie  # key rotated (no fixation)
    first = UserSession.objects.get(session_key=first_cookie)
    assert first.ended_reason == "LOGOUT"
    assert UserSession.objects.filter(ended_at__isnull=True).count() == 1


def test_deactivated_account_loses_access_immediately(signed_in):
    user, client = signed_in("alice")
    User.objects.filter(pk=user.pk).update(status=User.Status.INACTIVE)
    assert client.get("/api/v1/auth/me/").status_code == 401


# --- Lockout -----------------------------------------------------------------


def fail(new_client, username, times, **extra):
    return [sign_in(new_client(), username, WRONG, **extra) for _ in range(times)]


def test_lockout_blocks_even_the_correct_password(new_client, make_user):
    make_user("alice")
    assert {r.status_code for r in fail(new_client, "alice", 5)} == {401}

    response = sign_in(new_client(), "alice", PASSWORD)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"
    assert "sessionid" not in response.cookies
    assert not UserSession.objects.exists()


def test_lockout_message_is_identical_for_unknown_usernames(new_client, make_user):
    make_user("alice")
    fail(new_client, "alice", 5)
    fail(new_client, "ghost", 5)

    real = sign_in(new_client(), "alice", PASSWORD)
    unknown = sign_in(new_client(), "ghost", PASSWORD)

    assert real.status_code == unknown.status_code == 429
    assert real.content == unknown.content


def test_lockout_counts_username_case_insensitively(new_client, make_user):
    make_user("alice")
    for name in ("ALICE", "Alice", "alice", "aLiCe", "ALICE"):
        sign_in(new_client(), name, WRONG)
    assert sign_in(new_client(), "alice", PASSWORD).status_code == 429


def test_lockout_ends_when_old_failures_leave_the_window(new_client, make_user):
    make_user("alice")
    fail(new_client, "alice", 5)
    assert sign_in(new_client(), "alice", PASSWORD).status_code == 429

    LoginAttempt.objects.update(attempted_at=timezone.now() - timedelta(minutes=16))

    assert sign_in(new_client(), "alice", PASSWORD).status_code == 200


def test_throttled_attempts_do_not_extend_the_lockout(new_client, make_user):
    make_user("alice")
    fail(new_client, "alice", 5)
    for _ in range(3):  # blocked attempts while locked
        assert sign_in(new_client(), "alice", PASSWORD).status_code == 429

    LoginAttempt.objects.filter(failure_reason="BAD_CREDENTIALS").update(
        attempted_at=timezone.now() - timedelta(minutes=16)
    )

    assert sign_in(new_client(), "alice", PASSWORD).status_code == 200


def test_administrator_can_clear_a_lockout(new_client, make_user):
    user = make_user("alice")
    fail(new_client, "alice", 5)
    assert sign_in(new_client(), "alice", PASSWORD).status_code == 429

    User.objects.filter(pk=user.pk).update(lockout_reset_at=timezone.now())

    assert sign_in(new_client(), "alice", PASSWORD).status_code == 200


def test_a_successful_sign_in_resets_the_failure_count(new_client, make_user):
    make_user("alice")
    fail(new_client, "alice", 4)
    assert sign_in(new_client(), "alice", PASSWORD).status_code == 200
    fail(new_client, "alice", 4)

    assert sign_in(new_client(), "alice", WRONG).status_code == 401  # 5th failure still allowed
    assert sign_in(new_client(), "alice", WRONG).status_code == 429  # now blocked


def test_ip_address_limit_applies_across_usernames(new_client, make_user, settings):
    settings.TCOS_LOGIN_IP_MAX_FAILURES = 3
    make_user("alice")
    for name in ("ghost1", "ghost2", "ghost3"):
        sign_in(new_client(), name, WRONG, REMOTE_ADDR="10.0.0.5")

    assert sign_in(new_client(), "alice", PASSWORD, REMOTE_ADDR="10.0.0.5").status_code == 429
    assert sign_in(new_client(), "alice", PASSWORD, REMOTE_ADDR="10.0.0.6").status_code == 200


def test_forwarded_for_header_is_ignored_by_default(new_client, make_user):
    make_user("alice")
    sign_in(new_client(), "alice", WRONG, HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.9.9.9")
    assert LoginAttempt.objects.get().ip_address == "10.9.9.9"


def test_forwarded_for_header_is_used_behind_a_trusted_proxy(new_client, make_user, settings):
    settings.TCOS_TRUSTED_PROXY_COUNT = 1
    make_user("alice")
    sign_in(
        new_client(),
        "alice",
        WRONG,
        HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7",  # the first entry is attacker-controlled
        REMOTE_ADDR="10.9.9.9",
    )
    assert LoginAttempt.objects.get().ip_address == "203.0.113.7"


# --- Session timeouts ---------------------------------------------------------


def test_session_ends_after_the_absolute_time_limit(signed_in, settings):
    user, client = signed_in("alice")
    session = client.session
    session["login_at"] = int(time.time()) - settings.TCOS_SESSION_ABSOLUTE_SECONDS - 5
    session.save()

    assert client.get("/api/v1/auth/me/").status_code == 401

    assert UserSession.objects.get().ended_reason == "ABSOLUTE_TIMEOUT"
    assert client.get("/api/v1/auth/me/").status_code == 401  # stays ended


def test_session_not_created_by_sign_in_is_rejected(signed_in):
    user, client = signed_in("alice")
    session = client.session
    del session["login_at"]
    session.save()
    assert client.get("/api/v1/auth/me/").status_code == 401


def test_idle_session_expires(signed_in):
    user, client = signed_in("alice")
    key = UserSession.objects.get().session_key
    Session.objects.filter(session_key=key).update(
        expire_date=timezone.now() - timedelta(minutes=1)
    )

    assert client.get("/api/v1/auth/me/").status_code == 401

    assert list_active_sessions(user) == []
    assert UserSession.objects.get().ended_reason == "IDLE_TIMEOUT"


def test_last_activity_is_recorded(signed_in):
    user, client = signed_in("alice")
    record = UserSession.objects.get()
    session = client.session
    session["seen_at"] = int(time.time()) - 600  # pretend it was last updated 10 minutes ago
    session.save()
    UserSession.objects.filter(pk=record.pk).update(
        last_seen_at=timezone.now() - timedelta(minutes=10)
    )
    before = UserSession.objects.get().last_seen_at

    client.get("/api/v1/auth/me/")

    assert UserSession.objects.get().last_seen_at > before


# --- Forced password change ---------------------------------------------------

factory = APIRequestFactory()


class Probe(APIView):
    permission_classes = [IsSignedIn]

    def get(self, request):
        return Response({"ok": True})


class AllowedProbe(Probe):
    allow_password_change_pending = True


def test_pending_password_change_blocks_ordinary_endpoints(make_user):
    user = make_user("alice", must_change_password=True)

    request = factory.get("/x")
    force_authenticate(request, user=user)
    assert Probe.as_view()(request).status_code == 403

    request = factory.get("/x")
    force_authenticate(request, user=user)
    assert AllowedProbe.as_view()(request).status_code == 200


def test_account_endpoints_work_while_password_change_is_pending(new_client, make_user):
    make_user("alice", must_change_password=True)
    client = new_client()
    assert sign_in(client, "alice").json()["user"]["must_change_password"] is True
    assert client.get("/api/v1/auth/me/").status_code == 200
    assert client.get("/api/v1/auth/sessions/").status_code == 200
    assert post(client, "/api/v1/auth/logout/").status_code == 204

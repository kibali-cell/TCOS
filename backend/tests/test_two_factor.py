"""Two-factor sign-in: enrol, log in, recovery, disable, lockout, required roles."""

import base64

from apps.accounts import twofactor
from apps.accounts.models import RecoveryCode, TwoFactor, User
from apps.audit import events
from apps.audit.models import AuditEvent
from tests.conftest import PASSWORD, give_role, post, sign_in

BASE = "/api/v1/auth/2fa/"
LOGIN2 = "/api/v1/auth/login/2fa/"


def code_for(secret_b32, offset=0):
    return twofactor.totp_at(base64.b32decode(secret_b32), twofactor.current_step() + offset)


def enrol(client, user, offset=-1):
    """Enrol and confirm. Uses the previous step so later steps stay available for sign-in."""
    started = post(client, BASE + "enrol/")
    assert started.status_code == 200, started.content
    secret = started.json()["secret"]
    done = post(client, BASE + "confirm/", {"code": code_for(secret, offset)})
    assert done.status_code == 200, done.content
    return secret, done.json()["recovery_codes"]


def test_enrolment_shows_qr_stores_the_secret_encrypted_and_gives_recovery_codes(signed_in):
    user, client = signed_in("amina")
    started = post(client, BASE + "enrol/").json()
    assert started["qr"].startswith("data:image/svg+xml;base64,")
    assert started["otpauth_uri"].startswith("otpauth://totp/")
    record = TwoFactor.objects.get(user=user)
    assert started["secret"] not in record.secret_encrypted
    assert not record.is_enabled  # nothing on until a code is confirmed
    assert client.get(BASE).json()["enabled"] is False
    wrong = post(client, BASE + "confirm/", {"code": "000000"})
    assert wrong.status_code == 400
    assert not TwoFactor.objects.get(user=user).is_enabled
    ok = post(client, BASE + "confirm/", {"code": code_for(started["secret"], -1)})
    codes = ok.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert client.get(BASE).json()["enabled"] is True
    stored = list(RecoveryCode.objects.filter(user=user).values_list("code_hash", flat=True))
    assert not any(c.replace("-", "") in "".join(stored) for c in codes)  # hashed
    assert AuditEvent.objects.filter(event_type=events.TWO_FACTOR_ENABLED).count() == 1
    everything = str(list(AuditEvent.objects.values_list("changes", "metadata")))
    assert started["secret"] not in everything and codes[0] not in everything


def test_sign_in_needs_the_second_step(signed_in, new_client):
    user, client = signed_in("amina")
    secret, _ = enrol(client, user)
    fresh = new_client()
    first = sign_in(fresh, "amina")
    assert first.status_code == 200 and first.json() == {"two_factor_required": True}
    assert fresh.get("/api/v1/auth/me/").status_code in (401, 403)  # password alone is not enough
    done = post(fresh, LOGIN2, {"code": code_for(secret, 0)})
    assert done.status_code == 200
    assert fresh.get("/api/v1/auth/me/").status_code == 200


def test_a_used_code_cannot_be_replayed(signed_in, new_client):
    user, client = signed_in("amina")
    secret, _ = enrol(client, user)
    code = code_for(secret, 0)
    a = new_client()
    sign_in(a, "amina")
    assert post(a, LOGIN2, {"code": code}).status_code == 200
    b = new_client()
    sign_in(b, "amina")
    assert post(b, LOGIN2, {"code": code}).status_code == 401


def test_the_second_step_needs_the_first(new_client, signed_in):
    user, client = signed_in("amina")
    secret, _ = enrol(client, user)
    stranger = new_client()
    assert post(stranger, LOGIN2, {"code": code_for(secret, 0)}).status_code == 401


def test_recovery_code_works_once(signed_in, new_client):
    user, client = signed_in("amina")
    _, codes = enrol(client, user)
    a = new_client()
    sign_in(a, "amina")
    assert post(a, LOGIN2, {"code": codes[0], "recovery": True}).status_code == 200
    b = new_client()
    sign_in(b, "amina")
    assert post(b, LOGIN2, {"code": codes[0], "recovery": True}).status_code == 401
    assert AuditEvent.objects.filter(event_type=events.TWO_FACTOR_RECOVERY_USED).count() == 1
    assert RecoveryCode.objects.filter(user=user, used_at__isnull=False).count() == 1


def test_wrong_codes_lock_the_account_like_wrong_passwords(signed_in, new_client, settings):
    user, client = signed_in("amina")
    secret, _ = enrol(client, user)
    limit = settings.TCOS_LOGIN_MAX_FAILURES
    for _ in range(limit):
        attempt = new_client()
        assert sign_in(attempt, "amina").status_code == 200  # password step still fine
        assert post(attempt, LOGIN2, {"code": "123456"}).status_code == 401
    locked = new_client()
    blocked = sign_in(locked, "amina")
    assert blocked.status_code == 429
    # Even a correct code cannot get in while locked.
    assert post(locked, LOGIN2, {"code": code_for(secret, 0)}).status_code in (401, 429)
    assert locked.get("/api/v1/auth/me/").status_code in (401, 403)


def test_password_step_alone_is_not_counted_as_a_success(signed_in, new_client):
    """Otherwise a guessed password would reset the failure count between code guesses."""
    from apps.accounts.models import LoginAttempt

    user, client = signed_in("amina")
    enrol(client, user)
    before = LoginAttempt.objects.filter(user=user, success=True).count()
    for _ in range(3):
        attempt = new_client()
        sign_in(attempt, "amina")
        post(attempt, LOGIN2, {"code": "999999"})
    assert LoginAttempt.objects.filter(user=user, success=True).count() == before


def test_disable_needs_password_and_code_and_is_audited(signed_in):
    user, client = signed_in("amina")
    secret, _ = enrol(client, user)
    bad_pw = post(
        client, BASE + "disable/", {"password": "wrong-password-1", "code": code_for(secret, 0)}
    )
    assert bad_pw.status_code == 400
    bad_code = post(client, BASE + "disable/", {"password": PASSWORD, "code": "000000"})
    assert bad_code.status_code == 400
    assert twofactor.is_enabled(user)
    ok = post(client, BASE + "disable/", {"password": PASSWORD, "code": code_for(secret, 0)})
    assert ok.status_code == 200
    assert not twofactor.is_enabled(user)
    assert not RecoveryCode.objects.filter(user=user).exists()
    assert AuditEvent.objects.filter(event_type=events.TWO_FACTOR_DISABLED).count() == 1
    assert AuditEvent.objects.filter(event_type=events.TWO_FACTOR_FAILED).count() >= 1


def test_recovery_codes_can_be_renewed_and_old_ones_stop_working(signed_in):
    user, client = signed_in("amina")
    secret, old = enrol(client, user)
    new = post(
        client, BASE + "recovery-codes/", {"password": PASSWORD, "code": code_for(secret, 0)}
    )
    assert new.status_code == 200
    fresh = new.json()["recovery_codes"]
    assert set(fresh).isdisjoint(old)
    assert not twofactor.check_recovery_code(user, old[0])
    assert twofactor.check_recovery_code(user, fresh[0])


def test_cannot_enrol_twice_and_endpoints_need_sign_in(signed_in, new_client):
    user, client = signed_in("amina")
    enrol(client, user)
    assert post(client, BASE + "enrol/").status_code == 400
    anon = new_client()
    assert anon.get(BASE).status_code in (401, 403)
    assert post(anon, BASE + "enrol/").status_code in (401, 403)


def test_a_role_can_require_two_factor_and_the_server_enforces_it(staff, make_user, new_client):
    from apps.rbac.models import Role

    Role.objects.filter(code="FINANCE_OFFICER").update(requires_two_factor=True)
    user, client = staff("FINANCE_OFFICER", username="fin")
    me = client.get("/api/v1/auth/me/").json()
    assert me["two_factor"]["setup_required"] is True
    # Until set up, working endpoints are refused by the server, not just hidden.
    assert client.get("/api/v1/approvals/requests/").status_code == 403
    assert client.get("/api/v1/auth/me/").status_code == 200  # can still reach set-up
    secret, _ = enrol(client, user)
    assert client.get("/api/v1/approvals/requests/").status_code == 200
    # Required means it cannot be switched off.
    off = post(client, BASE + "disable/", {"password": PASSWORD, "code": code_for(secret, 0)})
    assert off.status_code == 403
    assert off.json()["error"]["code"] == "two_factor_required"


def test_administrator_reset_for_a_lost_phone_and_the_sensitive_exception(staff, make_user):
    _, admin = staff("ADMINISTRATOR")
    plain = make_user("plain")
    give_role(plain, "STOREKEEPER")
    plain_client = __import__("rest_framework.test", fromlist=["APIClient"]).APIClient(
        enforce_csrf_checks=True
    )
    sign_in(plain_client, "plain")
    enrol(plain_client, plain)
    url = f"/api/v1/users/{plain.pk}/reset-two-factor/"
    assert post(admin, url, {"reason": "lost phone"}).status_code == 200
    assert not twofactor.is_enabled(User.objects.get(pk=plain.pk))
    boss = make_user("boss")
    give_role(boss, "EXECUTIVE_DIRECTOR")
    TwoFactor.objects.create(user=boss, secret_encrypted="x", confirmed_at="2026-01-01T00:00:00Z")
    refused = post(admin, f"/api/v1/users/{boss.pk}/reset-two-factor/", {})
    assert refused.status_code == 403
    assert TwoFactor.objects.filter(user=boss).exists()

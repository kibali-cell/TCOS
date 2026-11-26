"""Two-factor sign-in with an authenticator app (TOTP, RFC 6238) and recovery codes.

* The secret is stored encrypted (AES-GCM, ``apps.core.crypto``), bound to the user's id.
* A code is accepted once only: the time step it belongs to is remembered.
* Recovery codes are random, shown once, kept as SHA-256 hashes and work once each.
* Turning it off, or making new recovery codes, asks for the password and a current code.
* A role can require two factor. A person who needs it but has not set it up can do nothing
  except set it up (``setup_blocked``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.audit import events as audit_events
from apps.audit.service import record as audit
from apps.core import crypto

from .models import RecoveryCode, TwoFactor, User

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept the previous and next step too, for clock drift
RECOVERY_CODE_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


# --- The algorithm ---------------------------------------------------------------------


def totp_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()  # noqa: S324 (RFC 6238)
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{number:0{DIGITS}d}"


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def _matching_step(secret: bytes, code: str, after_step: int) -> int | None:
    """The step the code belongs to, if it is current and has not been used before."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isascii() and code.isdigit() and len(code) == DIGITS):
        return None
    now = current_step()
    found = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(totp_at(secret, step), code) and step > after_step:
            found = step
    return found


def _secret_bytes(record: TwoFactor) -> bytes:
    text = crypto.decrypt(record.secret_encrypted, f"2fa:{record.user_id}")
    return base64.b32decode(text)


# --- State -----------------------------------------------------------------------------------


def is_enabled(user: User) -> bool:
    return TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).exists()


def is_required(user: User) -> bool:
    if user.two_factor_required:
        return True
    from apps.rbac.models import UserRole

    today = timezone.localdate()
    return (
        UserRole.objects.filter(
            user=user,
            revoked_at__isnull=True,
            role__is_active=True,
            role__requires_two_factor=True,
        )
        .filter(valid_to__isnull=True)
        .exists()
        or UserRole.objects.filter(
            user=user,
            revoked_at__isnull=True,
            role__is_active=True,
            role__requires_two_factor=True,
            valid_to__gte=today,
        ).exists()
    )


def setup_blocked(user: User) -> bool:
    """True when two factor is required of this person and not yet set up."""
    if not (user and user.is_authenticated):
        return False
    if is_enabled(user):
        return False
    return is_required(user)


def status_payload(user: User) -> dict:
    enabled = is_enabled(user)
    required = is_required(user)
    return {
        "enabled": enabled,
        "required": required,
        "setup_required": required and not enabled,
        "recovery_codes_left": RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
        if enabled
        else 0,
    }


# --- Enrolment -------------------------------------------------------------------------------


def _otpauth_uri(user: User, secret_b32: str) -> str:
    issuer = settings.TCOS_2FA_ISSUER
    label = quote(f"{issuer}:{user.username}")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _qr_svg_data_uri(text: str) -> str:
    import io

    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="svg", scale=5, border=2, xmldecl=False)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode()


@transaction.atomic
def begin_enrolment(user: User) -> dict:
    """Start (or restart) setup. Nothing is switched on until a code is confirmed."""
    if is_enabled(user):
        raise ApiValidationError({"detail": ["Two-factor sign-in is already switched on."]})
    secret_b32 = base64.b32encode(secrets.token_bytes(20)).decode()
    TwoFactor.objects.update_or_create(
        user=user,
        defaults={
            "secret_encrypted": crypto.encrypt(secret_b32, f"2fa:{user.pk}"),
            "confirmed_at": None,
            "last_used_step": 0,
        },
    )
    uri = _otpauth_uri(user, secret_b32)
    return {"secret": secret_b32, "otpauth_uri": uri, "qr": _qr_svg_data_uri(uri)}


def _new_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        RecoveryCode.objects.create(user=user, code_hash=_hash_recovery(codes[-1]))
    return codes


def _hash_recovery(code: str) -> str:
    cleaned = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(cleaned.encode()).hexdigest()


@transaction.atomic
def confirm_enrolment(user: User, code: str) -> list[str]:
    record = TwoFactor.objects.select_for_update().filter(user=user).first()
    if record is None or record.is_enabled:
        raise ApiValidationError({"detail": ["Start setup first."]})
    step = _matching_step(_secret_bytes(record), code, 0)
    if step is None:
        raise ApiValidationError(
            {"code": ["That code is not right. Check the time on your phone."]}
        )
    record.confirmed_at = timezone.now()
    record.last_used_step = step
    record.save(update_fields=["confirmed_at", "last_used_step"])
    codes = _new_recovery_codes(user)
    audit(
        audit_events.TWO_FACTOR_ENABLED,
        actor=user,
        object_type="accounts.User",
        object_id=user.pk,
    )
    return codes


# --- Checking a code at sign-in ---------------------------------------------------------


def check_code(user: User, code: str) -> bool:
    """True if ``code`` is a valid current code, which is then used up."""
    with transaction.atomic():
        record = TwoFactor.objects.select_for_update().filter(user=user).first()
        if record is None or not record.is_enabled:
            return False
        step = _matching_step(_secret_bytes(record), code, record.last_used_step)
        if step is None:
            return False
        record.last_used_step = step
        record.save(update_fields=["last_used_step"])
        return True


def check_recovery_code(user: User, code: str) -> bool:
    with transaction.atomic():
        row = (
            RecoveryCode.objects.select_for_update()
            .filter(user=user, code_hash=_hash_recovery(code or ""), used_at__isnull=True)
            .first()
        )
        if row is None:
            return False
        row.used_at = timezone.now()
        row.save(update_fields=["used_at"])
        audit(
            audit_events.TWO_FACTOR_RECOVERY_USED,
            actor=user,
            object_type="accounts.User",
            object_id=user.pk,
            metadata={"left": RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()},
        )
        return True


def _reauthenticate(user: User, password: str, code: str) -> None:
    """Password and a current code (or a recovery code) are both needed."""
    if not user.check_password(password or ""):
        raise ApiValidationError({"password": ["The password is not right."]})
    if not (check_code(user, code) or check_recovery_code(user, code)):
        audit(
            audit_events.TWO_FACTOR_FAILED,
            actor=user,
            success=False,
            object_type="accounts.User",
            object_id=user.pk,
            metadata={"during": "re-authentication"},
        )
        raise ApiValidationError({"code": ["That code is not right."]})


def disable(user: User, password: str, code: str) -> None:
    if is_required(user):
        raise PermissionDenied(
            "Two-factor sign-in is required for your account or role, so it cannot be "
            "switched off.",
            "two_factor_required",
        )
    if not is_enabled(user):
        raise ApiValidationError({"detail": ["Two-factor sign-in is not switched on."]})
    _reauthenticate(user, password, code)  # a refusal is audited, so not inside the block below
    with transaction.atomic():
        TwoFactor.objects.filter(user=user).delete()
        RecoveryCode.objects.filter(user=user).delete()
        audit(
            audit_events.TWO_FACTOR_DISABLED,
            actor=user,
            object_type="accounts.User",
            object_id=user.pk,
        )


def renew_recovery_codes(user: User, password: str, code: str) -> list[str]:
    if not is_enabled(user):
        raise ApiValidationError({"detail": ["Two-factor sign-in is not switched on."]})
    _reauthenticate(user, password, code)
    with transaction.atomic():
        codes = _new_recovery_codes(user)
        audit(
            audit_events.TWO_FACTOR_RECOVERY_RENEWED,
            actor=user,
            object_type="accounts.User",
            object_id=user.pk,
        )
    return codes


@transaction.atomic
def reset_for(actor: User | None, user: User, reason: str = "") -> None:
    """Remove someone's two-factor set-up (lost phone). The person must set it up again if it
    is required of them. Refused for anyone holding a sensitive role unless done from the server
    console (``actor`` is None), so an administrator cannot strip the protection from the
    accounts that matter most (D-077)."""
    from . import services

    if actor is not None:
        if actor.pk == user.pk:
            raise PermissionDenied("You cannot reset your own two-factor set-up.", "self_reset")
        if services._holds_sensitive_role(user):
            raise PermissionDenied(
                "This person holds a sensitive role, so their two-factor set-up can only be reset "
                "from the server console by the server operator.",
                "sensitive_account",
            )
    TwoFactor.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    from .models import UserSession

    services.end_all_sessions(user, UserSession.EndReason.PASSWORD_CHANGED, actor=actor)
    audit(
        audit_events.TWO_FACTOR_DISABLED,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=user.department_id,
        metadata={
            "reset": True,
            "by": actor.username if actor else "server console",
            "reason": reason[:300],
        },
    )

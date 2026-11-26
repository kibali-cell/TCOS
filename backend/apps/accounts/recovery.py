"""Password reset by e-mail.

* The link holds a random 256-bit token; only its SHA-256 is stored, it works once and expires.
* Asking for a link answers the same way whether or not the account exists, and the e-mail is
  sent in the background so the answer takes the same time.
* A successful reset ends every session of the person, audited.
* An administrator can ask for a link for someone else. The link goes only to the e-mail on
  record; the administrator never sees the token or any password.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.audit import events as audit_events
from apps.audit.service import record as audit

from . import services
from .models import PasswordResetRequest, PasswordResetToken, User, UserSession

logger = logging.getLogger(__name__)

GENERIC_REQUEST_MESSAGE = (
    "If an account matches, a link to choose a new password has been sent to its e-mail address. "
    "The link works once and expires soon."
)
INVALID_LINK_MESSAGE = "This link is not valid any more. Ask for a new one."


class ResetLinkRefused(APIException):
    status_code = 429
    default_detail = "A link was sent recently. Please wait before asking again."
    default_code = "reset_recently_sent"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _deliver(subject: str, body: str, to: str) -> None:
    """Send an e-mail without letting a failure, or its delay, show to the caller."""

    def work():
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        except Exception:  # noqa: BLE001 - mail servers fail in many ways; never leak details
            logger.warning("A password e-mail could not be sent.")

    if getattr(settings, "TCOS_EMAIL_ASYNC", True):
        threading.Thread(target=work, daemon=True).start()
    else:
        work()


def _new_token(user: User, requested_by: User | None = None) -> str:
    """Create a token (retiring earlier unused ones) and return the raw value."""
    now = timezone.now()
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    raw = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=_hash(raw),
        expires_at=now + timedelta(minutes=settings.TCOS_RESET_TOKEN_MINUTES),
        requested_by=requested_by,
    )
    return raw


def _send_link(user: User, raw: str, by_admin: bool) -> None:
    link = f"{settings.TCOS_PUBLIC_URL.rstrip('/')}/reset-password#token={raw}"
    minutes = settings.TCOS_RESET_TOKEN_MINUTES
    who = "An administrator has" if by_admin else "You have"
    body = (
        f"Hello {user.full_name},\n\n"
        f"{who} asked for a new password for your Tuleeni Children Operating System account "
        f"(username: {user.username}).\n\n"
        f"Choose a new password here (the link works once and expires in {minutes} minutes):\n"
        f"{link}\n\n"
        "If you did not expect this, ignore this e-mail; your password has not changed.\n"
    )
    _deliver("Choose a new TCOS password", body, user.email)


def _find(identifier: str) -> User | None:
    value = (identifier or "").strip().lower()[:254]
    if not value:
        return None
    return User.objects.filter(username=value).first() or User.objects.filter(email=value).first()


def request_reset(request, identifier: str) -> None:
    """Handle "I forgot my password". Never says whether the account exists."""
    value = (identifier or "").strip().lower()[:254]
    ip = services.get_client_ip(request)
    hashed = _hash(value)
    hour_ago = timezone.now() - timedelta(hours=1)

    # Throttle on every request, existing account or not, so the limits reveal nothing.
    by_account = PasswordResetRequest.objects.filter(
        identifier_hash=hashed, requested_at__gte=hour_ago
    ).count()
    by_ip = (
        PasswordResetRequest.objects.filter(ip_address=ip, requested_at__gte=hour_ago).count()
        if ip
        else 0
    )
    throttled = (
        by_account >= settings.TCOS_RESET_MAX_PER_ACCOUNT_HOUR
        or by_ip >= settings.TCOS_RESET_MAX_PER_IP_HOUR
    )
    user = None if throttled else _find(value)
    sent = bool(user and user.is_active and user.email)
    with transaction.atomic():
        PasswordResetRequest.objects.create(identifier_hash=hashed, ip_address=ip, sent=sent)
        raw = _new_token(user) if sent else None
        audit(
            audit_events.PASSWORD_RESET_REQUESTED,
            actor=None,
            object_type="accounts.User" if sent else "",
            object_id=user.pk if sent else "",
            metadata={"throttled": True} if throttled else {},
        )
    if sent:
        _send_link(user, raw, by_admin=False)


@transaction.atomic
def admin_send_link(actor: User, user: User) -> None:
    """Send ``user`` a reset link at their e-mail on record. The actor learns nothing secret."""
    if user.pk == actor.pk:
        raise PermissionDenied("Use Forgot password for your own account.", "self_reset")
    if not user.is_active:
        raise ApiValidationError({"detail": ["This account is not active."]})
    hour_ago = timezone.now() - timedelta(hours=1)
    recent = PasswordResetToken.objects.filter(user=user, created_at__gte=hour_ago).count()
    if recent >= settings.TCOS_RESET_MAX_PER_ACCOUNT_HOUR:
        raise ResetLinkRefused()
    raw = _new_token(user, requested_by=actor)
    audit(
        audit_events.PASSWORD_RESET_LINK_SENT,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=user.department_id,
    )
    transaction.on_commit(lambda: _send_link(user, raw, by_admin=True))


def confirm_reset(request, raw_token: str, new_password: str) -> None:
    """Set the new password if the token is valid; otherwise say only that the link is bad."""
    ip = services.get_client_ip(request)
    with transaction.atomic():
        token = (
            PasswordResetToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash(raw_token or ""))
            .first()
        )
        now = timezone.now()
        if (
            token is None
            or token.used_at is not None
            or token.expires_at <= now
            or not token.user.is_active
        ):
            token = None
        else:
            user = token.user
    if token is None:
        # Recorded outside the block above so the entry survives the refusal.
        audit(
            audit_events.PASSWORD_RESET_FAILED,
            actor=None,
            success=False,
            metadata={"ip": ip} if ip else {},
        )
        raise ApiValidationError({"token": [INVALID_LINK_MESSAGE]})
    with transaction.atomic():
        token = PasswordResetToken.objects.select_for_update().get(pk=token.pk)
        if token.used_at is not None:
            raise ApiValidationError({"token": [INVALID_LINK_MESSAGE]})
        user = token.user
        try:
            password_validation.validate_password(new_password, user)
        except DjangoValidationError as exc:
            # The link stays usable so the person can try a better password.
            raise ApiValidationError({"new_password": list(exc.messages)}) from exc

        user.set_password(new_password)
        user.must_change_password = False
        user.password_changed_at = now
        user.lockout_reset_at = now
        user.save(
            update_fields=[
                "password",
                "must_change_password",
                "password_changed_at",
                "lockout_reset_at",
                "updated_at",
            ]
        )
        token.used_at = now
        token.save(update_fields=["used_at"])
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
        ended = services.end_all_sessions(
            user, UserSession.EndReason.PASSWORD_CHANGED, actor=None, audited=False
        )
        audit(
            audit_events.PASSWORD_RESET_COMPLETED,
            actor=user,
            object_type="accounts.User",
            object_id=user.pk,
            metadata={
                "sessions_ended": ended,
                "started_by_admin": token.requested_by_id is not None,
            },
        )
    _deliver(
        "Your TCOS password was changed",
        f"Hello {user.full_name},\n\nYour password was just changed using a reset link. "
        "You have been signed out everywhere. If this was not you, tell an administrator now.\n",
        user.email,
    )

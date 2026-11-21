"""Account business logic: creation, sign-in, sessions, password change.

Views stay thin and call these functions. Nothing here logs passwords, session
keys or other secrets.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    password_validation,
    update_session_auth_hash,
)
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as ApiValidationError

from .models import LoginAttempt, User, UserSession, normalise_email, normalise_username

logger = logging.getLogger(__name__)

THROTTLED = "THROTTLED"
SEEN_UPDATE_SECONDS = 60


class InvalidCredentials(APIException):
    """Same response for unknown user, wrong password and inactive account."""

    status_code = 401
    default_detail = "Invalid username or password."
    default_code = "invalid_credentials"


class TooManyAttempts(APIException):
    """Same response whether or not the username exists."""

    status_code = 429
    default_detail = "Too many failed sign-in attempts. Please wait a few minutes and try again."
    default_code = "too_many_attempts"


# --- Request helpers -------------------------------------------------------


def get_client_ip(request) -> str | None:
    """Client address. X-Forwarded-For is only used behind trusted proxies."""
    proxies = settings.TCOS_TRUSTED_PROXY_COUNT
    candidate = None
    if proxies > 0:
        parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
        parts = [p for p in parts if p]
        if len(parts) >= proxies:
            candidate = parts[-proxies]
    if candidate is None:
        candidate = request.META.get("REMOTE_ADDR")
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


_OS_TOKENS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Mac OS X", "Mac"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)
_BROWSER_TOKENS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)


def describe_device(user_agent: str) -> str:
    """Short human label such as 'Chrome on Windows'."""
    ua = user_agent or ""
    system = next((label for token, label in _OS_TOKENS if token in ua), "Unknown system")
    browser = next((label for token, label in _BROWSER_TOKENS if token in ua), "Browser")
    return f"{browser} on {system}"


# --- Account creation ------------------------------------------------------


def create_user(
    *,
    username: str,
    email: str,
    full_name: str,
    password: str,
    phone: str = "",
    status: str = User.Status.ACTIVE,
    is_superuser: bool = False,
    must_change_password: bool = False,
    department=None,
    created_by: User | None = None,
) -> User:
    """Create an account, enforcing field validation and the password policy.

    Raises ``django.core.exceptions.ValidationError`` when anything is invalid.
    """
    user = User(
        username=normalise_username(username),
        email=normalise_email(email),
        full_name=(full_name or "").strip(),
        phone=(phone or "").strip(),
        status=status,
        is_superuser=is_superuser,
        must_change_password=must_change_password,
        department=department,
        created_by=created_by,
    )
    user.full_clean(exclude=["password"])
    password_validation.validate_password(password, user)
    user.set_password(password)
    user.password_changed_at = timezone.now()
    user.save()
    return user


# --- Sign-in ---------------------------------------------------------------


def _record_attempt(request, username, user, success, reason=""):
    LoginAttempt.objects.create(
        username_attempted=username,
        user=user,
        success=success,
        failure_reason=reason,
        ip_address=get_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:400],
    )


def is_blocked(username: str, user: User | None, ip: str | None) -> bool:
    """True when too many recent failures exist for this username or IP.

    The check is identical for existing and non-existing usernames, so it does
    not reveal which accounts exist. Throttled attempts are not counted, so an
    attacker cannot keep an account locked indefinitely.
    """
    now = timezone.now()
    window_start = now - timedelta(minutes=settings.TCOS_LOGIN_WINDOW_MINUTES)
    failures = LoginAttempt.objects.filter(success=False).exclude(failure_reason=THROTTLED)

    cutoff = window_start
    if user is not None and user.lockout_reset_at:
        cutoff = max(cutoff, user.lockout_reset_at)
    last_success = LoginAttempt.objects.filter(username_attempted=username, success=True).aggregate(
        latest=Max("attempted_at")
    )["latest"]
    if last_success:
        cutoff = max(cutoff, last_success)

    if (
        failures.filter(username_attempted=username, attempted_at__gt=cutoff).count()
        >= settings.TCOS_LOGIN_MAX_FAILURES
    ):
        return True
    return bool(
        ip
        and failures.filter(ip_address=ip, attempted_at__gte=window_start).count()
        >= settings.TCOS_LOGIN_IP_MAX_FAILURES
    )


def sign_in(request, username: str, password: str) -> User:
    """Validate credentials, record the attempt and start a session."""
    name = normalise_username(username)[:150]
    user = User.objects.filter(username=name).first()
    ip = get_client_ip(request)

    if is_blocked(name, user, ip):
        _record_attempt(request, name, user, False, THROTTLED)
        raise TooManyAttempts()

    authenticated = authenticate(request, username=name, password=password)
    if authenticated is None:
        reason = "BAD_CREDENTIALS"
        if user is not None and not user.is_active and user.check_password(password):
            reason = "ACCOUNT_NOT_ACTIVE"
        _record_attempt(request, name, user, False, reason)
        raise InvalidCredentials()

    _record_attempt(request, name, authenticated, True)
    _start_session(request, authenticated)
    return authenticated


def _start_session(request, user: User) -> UserSession:
    previous_key = request.session.session_key
    if previous_key:
        # Django's login() keeps the key when the same user is already signed in.
        # Always start from a brand-new session so a key is never reused.
        _mark_ended(
            UserSession.objects.filter(session_key=previous_key, ended_at__isnull=True),
            UserSession.EndReason.LOGOUT,
        )
        request.session.flush()
    login(request, user)  # creates a fresh key and updates last_login
    if not request.session.session_key:
        request.session.save()
    now = int(time.time())
    request.session["login_at"] = now
    request.session["seen_at"] = now

    user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:400]
    return UserSession.objects.create(
        user=user,
        session_key=request.session.session_key,
        ip_address=get_client_ip(request),
        user_agent=user_agent,
        device_label=describe_device(user_agent),
    )


# --- Sessions --------------------------------------------------------------


def _mark_ended(queryset, reason: str) -> None:
    queryset.update(ended_at=timezone.now(), ended_reason=reason)


def end_session(user_session: UserSession, reason: str) -> None:
    """End one session immediately by deleting its server-side session."""
    Session.objects.filter(session_key=user_session.session_key).delete()
    if user_session.ended_at is None:
        user_session.ended_at = timezone.now()
        user_session.ended_reason = reason
        user_session.save(update_fields=["ended_at", "ended_reason"])


def end_current_session(request, reason: str) -> None:
    """End the request's own session and clear the cookie."""
    key = request.session.session_key
    if key:
        _mark_ended(UserSession.objects.filter(session_key=key, ended_at__isnull=True), reason)
    logout(request)


def end_other_sessions(user: User, keep_key: str | None, reason: str) -> int:
    """End every active session of ``user`` except ``keep_key``. Returns the count."""
    sessions = UserSession.objects.filter(user=user, ended_at__isnull=True)
    if keep_key:
        sessions = sessions.exclude(session_key=keep_key)
    count = 0
    for user_session in sessions:
        end_session(user_session, reason)
        count += 1
    return count


def end_all_sessions(user: User, reason: str) -> int:
    return end_other_sessions(user, None, reason)


def list_active_sessions(user: User) -> list[UserSession]:
    """Active sessions, newest activity first. Dead sessions are marked ended."""
    rows = list(
        UserSession.objects.filter(user=user, ended_at__isnull=True).order_by("-last_seen_at")
    )
    alive = set(
        Session.objects.filter(
            session_key__in=[row.session_key for row in rows], expire_date__gt=timezone.now()
        ).values_list("session_key", flat=True)
    )
    active = []
    for row in rows:
        if row.session_key in alive:
            active.append(row)
        else:
            row.ended_at = timezone.now()
            row.ended_reason = UserSession.EndReason.IDLE_TIMEOUT
            row.save(update_fields=["ended_at", "ended_reason"])
    return active


def touch_session(session_key: str | None) -> None:
    if session_key:
        UserSession.objects.filter(session_key=session_key, ended_at__isnull=True).update(
            last_seen_at=timezone.now()
        )


# --- Password change -------------------------------------------------------


@transaction.atomic
def change_password(request, user: User, current_password: str, new_password: str) -> int:
    """Change the user's password and end all their other sessions.

    Returns the number of other sessions that were ended.
    """
    if not user.check_password(current_password):
        raise ApiValidationError({"current_password": ["The current password is incorrect."]})
    if current_password == new_password:
        raise ApiValidationError(
            {"new_password": ["The new password must be different from the current one."]}
        )
    try:
        password_validation.validate_password(new_password, user)
    except DjangoValidationError as exc:
        raise ApiValidationError({"new_password": list(exc.messages)}) from exc

    user.set_password(new_password)
    user.password_changed_at = timezone.now()
    user.must_change_password = False
    user.save(
        update_fields=["password", "password_changed_at", "must_change_password", "updated_at"]
    )

    # Django rotates the session key when it refreshes the session hash; keep our record in step.
    old_key = request.session.session_key
    update_session_auth_hash(request, user)
    new_key = request.session.session_key
    if old_key and new_key and old_key != new_key:
        UserSession.objects.filter(session_key=old_key).update(session_key=new_key)

    return end_other_sessions(user, new_key, UserSession.EndReason.PASSWORD_CHANGED)

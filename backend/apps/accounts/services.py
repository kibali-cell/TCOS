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
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.audit import events as audit_events
from apps.audit.service import record as audit

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

PROFILE_FIELDS = ("username", "email", "full_name", "phone", "status", "department_id")


def _profile(user: User) -> dict:
    """The user fields worth recording. Never includes the password or its hash."""
    return {name: getattr(user, name) for name in PROFILE_FIELDS}


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
    with transaction.atomic():
        user.save()
        audit(
            audit_events.USER_CREATED,
            actor=created_by,
            object_type="accounts.User",
            object_id=user.pk,
            department_id=user.department_id,
            changes={name: {"from": None, "to": value} for name, value in _profile(user).items()},
            metadata={"created_by_system": created_by is None},
        )
    return user


# --- Sign-in ---------------------------------------------------------------


def _record_attempt(request, username, user, success, reason=""):
    """Record the attempt for throttling and write the matching audit event, together."""
    if success:
        event_type = audit_events.LOGIN_SUCCESS
    elif reason == THROTTLED:
        event_type = audit_events.LOGIN_BLOCKED
    else:
        event_type = audit_events.LOGIN_FAILED
    with transaction.atomic():
        LoginAttempt.objects.create(
            username_attempted=username,
            user=user,
            success=success,
            failure_reason=reason,
            ip_address=get_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:400],
        )
        audit(
            event_type,
            actor=user if success else None,
            actor_username=username,
            object_type="accounts.User" if user else "",
            object_id=user.pk if user else "",
            success=success,
            metadata={"reason": reason} if reason else {},
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

    with transaction.atomic():
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
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    key = request.session.session_key
    with transaction.atomic():
        if key:
            _mark_ended(UserSession.objects.filter(session_key=key, ended_at__isnull=True), reason)
        if user is not None:
            event = (
                audit_events.LOGOUT
                if reason == UserSession.EndReason.LOGOUT
                else audit_events.SESSION_ENDED
            )
            audit(
                event,
                actor=user,
                object_type="accounts.User",
                object_id=user.pk,
                metadata={"reason": reason},
            )
    logout(request)


def sign_out_device(user: User, user_session: UserSession) -> None:
    """The user ends one of their own other sessions."""
    with transaction.atomic():
        end_session(user_session, UserSession.EndReason.SIGNED_OUT_BY_USER)
        audit(
            audit_events.SESSION_ENDED,
            actor=user,
            object_type="accounts.UserSession",
            object_id=user_session.pk,
            metadata={
                "reason": UserSession.EndReason.SIGNED_OUT_BY_USER,
                "device": user_session.device_label,
            },
        )


def end_other_sessions(
    user: User,
    keep_key: str | None,
    reason: str,
    *,
    actor: User | None = None,
    audited: bool = True,
) -> int:
    """End every active session of ``user`` except ``keep_key``. Returns the count.

    One audit event is written for the whole operation (not one per session), unless the
    caller records its own event (``audited=False``).
    """
    sessions = UserSession.objects.filter(user=user, ended_at__isnull=True)
    if keep_key:
        sessions = sessions.exclude(session_key=keep_key)
    with transaction.atomic():
        count = 0
        for user_session in sessions:
            end_session(user_session, reason)
            count += 1
        if audited and count:
            audit(
                audit_events.SESSIONS_ENDED,
                actor=actor or user,
                object_type="accounts.User",
                object_id=user.pk,
                metadata={"reason": reason, "count": count},
            )
    return count


def end_all_sessions(
    user: User, reason: str, *, actor: User | None = None, audited: bool = True
) -> int:
    return end_other_sessions(user, None, reason, actor=actor, audited=audited)


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

    ended = end_other_sessions(user, new_key, UserSession.EndReason.PASSWORD_CHANGED, audited=False)
    audit(
        audit_events.PASSWORD_CHANGED,
        actor=user,
        object_type="accounts.User",
        object_id=user.pk,
        metadata={"ended_other_sessions": ended},
    )
    return ended


# --- Account changes ---------------------------------------------------------


@transaction.atomic
def update_user(actor: User, user: User, **fields) -> User:
    """Change profile fields (full_name, email, phone). Audited with a diff.

    A person's department is not edited here: it follows their main staff assignment
    (``apps.organisation.services``), which is what department-scoped access reads.
    """
    allowed = {"full_name", "email", "phone"}
    unknown = set(fields) - allowed
    if unknown:
        raise ApiValidationError({"detail": [f"Cannot change: {', '.join(sorted(unknown))}."]})
    before = _profile(user)
    for name, value in fields.items():
        setattr(user, name, value)
    user.email = normalise_email(user.email)
    user.full_name = (user.full_name or "").strip()
    user.phone = (user.phone or "").strip()
    try:
        user.full_clean(exclude=["password"])
    except DjangoValidationError as exc:
        raise ApiValidationError(exc.message_dict) from exc
    user.save()
    after = _profile(user)
    changes = {
        name: {"from": before[name], "to": after[name]}
        for name in after
        if before[name] != after[name]
    }
    if changes:
        audit(
            audit_events.USER_UPDATED,
            actor=actor,
            object_type="accounts.User",
            object_id=user.pk,
            department_id=user.department_id,
            changes=changes,
        )
    return user


@transaction.atomic
def set_user_status(actor: User, user: User, new_status: str, reason: str = "") -> User:
    """Activate or deactivate an account. Leaving ACTIVE ends all of the person's sessions."""
    if new_status not in User.Status.values:
        raise ApiValidationError({"status": ["Unknown status."]})
    if user.pk == actor.pk:
        raise PermissionDenied("You cannot change your own account status.", "self_deactivation")
    old_status = user.status
    if old_status == new_status:
        return user
    if old_status == User.Status.ACTIVE:
        from apps.rbac.services import working_administrators  # late import: avoid a cycle

        admins = working_administrators()
        if user.pk in admins and admins == {user.pk}:
            raise ApiValidationError(
                {"detail": ["This is the last working Administrator and cannot be deactivated."]}
            )
    user.status = new_status
    user.save(update_fields=["status", "updated_at"])
    if old_status != User.Status.ACTIVE and new_status == User.Status.ACTIVE:
        event = audit_events.USER_ACTIVATED
    elif old_status == User.Status.ACTIVE:
        event = audit_events.USER_DEACTIVATED
    else:
        event = audit_events.USER_UPDATED
    audit(
        event,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=user.department_id,
        changes={"status": {"from": old_status, "to": new_status}},
        metadata={"reason": (reason or "")[:300]},
    )
    if new_status != User.Status.ACTIVE:
        end_all_sessions(user, UserSession.EndReason.USER_DEACTIVATED, actor=actor)
    return user


# --- Administrator actions on other people's accounts (Slice 6) ---------------------------


def generate_temporary_password() -> str:
    """A random one-time password. Shown once to the administrator who sets it."""
    import secrets

    return secrets.token_urlsafe(12)


@transaction.atomic
def admin_create_user(actor: User, *, username: str, email: str, full_name: str, phone: str = ""):
    """Create an account with a random temporary password the person must change at once.

    Returns ``(user, temporary_password)``. The department is not set here: it follows the
    person's main staff assignment (D-056). Roles are given separately (sensitive roles only
    through the Approval Centre, D-065).
    """
    temporary = generate_temporary_password()
    try:
        user = create_user(
            username=username,
            email=email,
            full_name=full_name,
            phone=phone,
            password=temporary,
            must_change_password=True,
            created_by=actor,
        )
    except DjangoValidationError as exc:
        raise ApiValidationError(exc.message_dict) from exc
    return user, temporary


def _holds_sensitive_role(user: User) -> bool:
    from apps.rbac import services as rbac_services
    from apps.rbac.models import UserRole

    today = timezone.localdate()
    roles = [
        row.role
        for row in UserRole.objects.filter(user=user, revoked_at__isnull=True)
        .select_related("role")
        .filter(role__is_active=True)
        if (row.valid_to is None or row.valid_to >= today)
    ]
    return any(rbac_services.role_sensitivity(role) for role in roles)


@transaction.atomic
def admin_reset_password(actor: User, user: User) -> str:
    """Set a new random temporary password; ends the person's sessions. Returns it once.

    Refused for yourself, and for anyone who holds a sensitive role: whoever sees a
    temporary password could sign in as that person, which would get around the second-person
    approval needed to hold that role (D-072). Slice 7 replaces this with an e-mailed link.
    """
    if user.pk == actor.pk:
        raise PermissionDenied("Use Change password on your own account.", "self_reset")
    if _holds_sensitive_role(user):
        raise PermissionDenied(
            "This person holds a sensitive role, so a password cannot be set for them here. "
            "Password reset by e-mail arrives in a later release.",
            "sensitive_account",
        )
    temporary = generate_temporary_password()
    try:
        password_validation.validate_password(temporary, user)
    except DjangoValidationError as exc:  # practically impossible for a random value
        raise ApiValidationError({"detail": list(exc.messages)}) from exc
    user.set_password(temporary)
    user.must_change_password = True
    user.password_changed_at = timezone.now()
    user.save(
        update_fields=["password", "must_change_password", "password_changed_at", "updated_at"]
    )
    audit(
        audit_events.USER_PASSWORD_RESET,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=user.department_id,
        metadata={"sessions_ended": True},
    )
    end_all_sessions(user, UserSession.EndReason.PASSWORD_CHANGED, actor=actor)
    return temporary


@transaction.atomic
def unlock_user(actor: User, user: User) -> User:
    """Clear a sign-in lockout: only failures after this moment count again."""
    user.lockout_reset_at = timezone.now()
    user.save(update_fields=["lockout_reset_at", "updated_at"])
    audit(
        audit_events.USER_UNLOCKED,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=user.department_id,
    )
    return user

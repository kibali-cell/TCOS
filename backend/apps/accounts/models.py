import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

USERNAME_VALIDATOR = RegexValidator(
    r"^[a-z0-9][a-z0-9._-]{2,149}$",
    "Usernames use lower-case letters, digits, dots, dashes and underscores (3 to 150 characters).",
)
PHONE_VALIDATOR = RegexValidator(
    r"^\+?[0-9 ()-]{7,20}$",
    "Enter a valid phone number, for example +255 700 000 000.",
)


def normalise_username(value: str) -> str:
    return (value or "").strip().lower()


def normalise_email(value: str) -> str:
    return (value or "").strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        return self.get(username=normalise_username(username))


class User(AbstractBaseUser):
    """Institutional user account.

    Usernames and e-mail addresses are stored lower-case (enforced by CHECK
    constraints), so uniqueness is case-insensitive without needing a database
    extension. ``is_active`` is derived from ``status``.

    Department and position links are added in Slice 4, roles in Slice 2.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        LOCKED = "LOCKED", "Locked by an administrator"
        PENDING = "PENDING", "Pending activation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, validators=[USERNAME_VALIDATOR])
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32, blank=True, validators=[PHONE_VALIDATOR])

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # Reserved for emergency break-glass use. Day-to-day administrators use the
    # Administrator role (Slice 2).
    is_superuser = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    # Administrators clear a lockout by setting this; only failures after it count.
    lockout_reset_at = models.DateTimeField(null=True, blank=True)
    two_factor_required = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Primary department. DEPARTMENT-scoped permissions apply to this department unless the
    # role assignment names another. Slice 4 keeps it in step with staff assignments.
    department = models.ForeignKey(
        "organisation.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(username=Lower("username")), name="user_username_lowercase"
            ),
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")), name="user_email_lowercase"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["ACTIVE", "INACTIVE", "LOCKED", "PENDING"]),
                name="user_status_valid",
            ),
        ]
        indexes = [models.Index(fields=["status"], name="user_status_idx")]

    def __str__(self) -> str:
        return self.username

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.status == self.Status.ACTIVE

    def save(self, *args, **kwargs):
        self.username = normalise_username(self.username)
        self.email = normalise_email(self.email)
        super().save(*args, **kwargs)


class LoginAttempt(models.Model):
    """Every sign-in attempt, successful or not. Mirrored to the audit log in Slice 3."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username_attempted = models.CharField(max_length=150)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    success = models.BooleanField()
    # Internal only, never shown to the client.
    failure_reason = models.CharField(max_length=32, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["username_attempted", "attempted_at"], name="login_user_time_idx"),
            models.Index(fields=["ip_address", "attempted_at"], name="login_ip_time_idx"),
        ]

    def __str__(self):
        outcome = "ok" if self.success else (self.failure_reason or "failed")
        return f"{self.username_attempted} ({outcome})"


class UserSession(models.Model):
    """One signed-in browser or device, so users can see and end their sessions.

    ``session_key`` is the key of the matching server-side Django session. It is
    stored so a session can be ended instantly; it is never sent to clients, and
    the same value already exists in the Django session table. Slice 8 links
    sessions to registered devices.
    """

    class EndReason(models.TextChoices):
        LOGOUT = "LOGOUT", "Signed out"
        IDLE_TIMEOUT = "IDLE_TIMEOUT", "Inactive for too long"
        ABSOLUTE_TIMEOUT = "ABSOLUTE_TIMEOUT", "Maximum session length reached"
        SIGNED_OUT_BY_USER = "SIGNED_OUT_BY_USER", "Signed out from another device"
        PASSWORD_CHANGED = "PASSWORD_CHANGED", "Password changed"
        USER_DEACTIVATED = "USER_DEACTIVATED", "Account deactivated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    device_label = models.CharField(max_length=100, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=24, choices=EndReason.choices, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "ended_at"], name="usersession_user_end_idx")]

    def __str__(self):
        return f"{self.device_label or 'Device'} ({self.user_id})"

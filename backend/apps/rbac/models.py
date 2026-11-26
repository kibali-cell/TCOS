import uuid

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import F, Q

from .constants import ACTIONS, SCOPES


def _in(column: str, values) -> Q:
    return Q(**{f"{column}__in": list(values)})


ACTION_CHOICES = [(a, a) for a in ACTIONS]
SCOPE_CHOICES = [(s, s) for s in SCOPES]


class Permission(models.Model):
    """A (module, action) pair. Seeded; extended when later phases add modules."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.CharField(max_length=60)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["module", "action"], name="uniq_permission_module_action"
            ),
            models.CheckConstraint(
                condition=_in("action", ACTIONS), name="permission_action_valid"
            ),
        ]
        ordering = ["module", "action"]

    def __str__(self):
        return f"{self.module}.{self.action}"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_system = models.BooleanField(default=False)  # seeded roles cannot be deleted
    is_active = models.BooleanField(default=True)
    # Everyone holding this role must sign in with a second factor (Slice 7).
    requires_two_factor = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    """One independently assigned grant: this role may do `permission` within `scope`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="+")
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission"),
            models.CheckConstraint(
                condition=_in("scope", SCOPES), name="role_permission_scope_valid"
            ),
        ]

    def __str__(self):
        return f"{self.role_id} {self.permission_id} {self.scope}"


class UserRole(models.Model):
    """A role held by a user. May be limited to one department and to a date range.

    Revoking sets ``revoked_at``; rows are kept as history.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")
    department = models.ForeignKey(
        "organisation.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            # One live assignment per (user, role, department); NULL department is its own case.
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=Q(revoked_at__isnull=True, department__isnull=True),
                name="uniq_live_user_role_no_department",
            ),
            models.UniqueConstraint(
                fields=["user", "role", "department"],
                condition=Q(revoked_at__isnull=True, department__isnull=False),
                name="uniq_live_user_role_department",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=F("valid_from")),
                name="user_role_valid_range",
            ),
        ]
        indexes = [models.Index(fields=["user", "revoked_at"], name="user_role_user_live_idx")]

    def __str__(self):
        return f"{self.user_id} as {self.role_id}"


class RecordGrant(models.Model):
    """Access to one specific record for one action, independent of role scope."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="record_grants"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")
    object_id = models.UUIDField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    expires_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=_in("action", ACTIONS), name="record_grant_action_valid"
            ),
        ]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="record_grant_object_idx"),
            models.Index(fields=["user"], name="record_grant_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} {self.action} {self.content_type_id}:{self.object_id}"

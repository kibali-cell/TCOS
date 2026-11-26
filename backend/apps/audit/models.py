from django.db import models


class ImmutableAuditError(Exception):
    """Raised by any attempt to change or remove audit history."""


class AuditQuerySet(models.QuerySet):
    """Read-only: every write method other than the service's own insert is refused."""

    def _refuse(self, *args, **kwargs):
        raise ImmutableAuditError("The audit log is append-only.")

    update = delete = bulk_update = bulk_create = update_or_create = _refuse


class AuditEvent(models.Model):
    """One thing that happened. Append-only, enforced three ways:

    1. Application: this model refuses update and delete, and the only way to insert is
       ``apps.audit.service.record`` (which also maintains the hash chain).
    2. Database trigger: UPDATE, DELETE and TRUNCATE raise for every role.
    3. Database privileges: the role the application runs as has INSERT and SELECT only
       (see ``manage.py setup_database_roles`` and docs/ADMIN_SETUP.md).
    """

    # A plain bigserial so insertion order is strict and cheap.
    id = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_username = models.CharField(max_length=150, blank=True)  # snapshot
    event_type = models.CharField(max_length=60)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(
        "organisation.Department", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    prev_hash = models.CharField(max_length=64)
    event_hash = models.CharField(max_length=64, unique=True)

    objects = AuditQuerySet.as_manager()

    # Scope support for the permission engine: "own" means events I performed, and
    # department-scoped viewers see their department's events.
    RBAC_DEPARTMENT_FIELD = "department_id"
    RBAC_OWNER_FIELDS = ("actor_id",)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["occurred_at"], name="audit_occurred_idx"),
            models.Index(fields=["actor", "occurred_at"], name="audit_actor_idx"),
            models.Index(fields=["event_type", "occurred_at"], name="audit_type_idx"),
            models.Index(fields=["object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["department", "occurred_at"], name="audit_dept_idx"),
        ]

    def __str__(self):
        return f"#{self.id} {self.event_type}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableAuditError("Audit events cannot be modified.")
        if not getattr(self, "_from_service", False):
            raise ImmutableAuditError("Audit events are created only by audit.record().")
        super().save(
            *args, force_insert=True, **{k: v for k, v in kwargs.items() if k != "force_insert"}
        )

    def delete(self, *args, **kwargs):
        raise ImmutableAuditError("Audit events cannot be deleted.")

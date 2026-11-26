"""Organisation structure: departments, positions, staff assignments, approval chains.

These are reference data. Devices will read departments, positions and the staff directory
offline later (HYBRID_ARCHITECTURE section 4) but never change them offline, so every model
declares a ``SYNC_POLICY``. They follow the sync-ready conventions: UUID keys, an integer
``version`` that rises on every change, ``updated_by``, and archival instead of deletion.
All changes go through ``apps.organisation.services``.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

# What a device may do with each kind of record (enforced from Slice 9).
REFERENCE_READ_ONLY = {
    "offline_read": True,
    "offline_write": False,
    "conflict": "SERVER_WINS",
    "classification": "INTERNAL",
}
ONLINE_ONLY = {
    "offline_read": False,
    "offline_write": False,
    "conflict": "SERVER_WINS",
    "classification": "INTERNAL",
}

DEFAULT_REQUEST_TYPE = "DEFAULT"


class _Tracked(models.Model):
    """Columns every organisation record carries."""

    # Not audited: it changes on every save and says nothing the audit event time does not.
    AUDIT_EXCLUDE_FIELDS = ("updated_at",)

    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class _Archivable(models.Model):
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class Department(_Tracked, _Archivable):
    SYNC_POLICY = REFERENCE_READ_ONLY
    # Department-scoped audit viewing and access use the department itself.
    RBAC_DEPARTMENT_FIELD = "id"
    AUDIT_DEPARTMENT_FIELD = "id"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(parent=F("id")), name="department_not_its_own_parent"
            ),
            models.CheckConstraint(
                condition=Q(is_archived=False) | Q(is_active=False),
                name="department_archived_is_inactive",
            ),
            models.CheckConstraint(
                condition=Q(is_archived=True, archived_at__isnull=False)
                | Q(is_archived=False, archived_at__isnull=True),
                name="department_archive_stamp",
            ),
        ]

    def __str__(self):
        return self.name


class Position(_Tracked, _Archivable):
    SYNC_POLICY = REFERENCE_READ_ONLY
    RBAC_DEPARTMENT_FIELD = "department_id"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="positions")
    reports_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="direct_reports"
    )
    is_department_head_position = models.BooleanField(default=False)

    class Meta:
        ordering = ["department__name", "title"]
        constraints = [
            models.UniqueConstraint(fields=["department", "title"], name="position_title_unique"),
            models.CheckConstraint(
                condition=~Q(reports_to=F("id")), name="position_not_its_own_boss"
            ),
            models.UniqueConstraint(
                fields=["department"],
                condition=Q(is_department_head_position=True, is_archived=False),
                name="position_one_head_per_department",
            ),
            models.CheckConstraint(
                condition=Q(is_archived=False) | Q(is_active=False),
                name="position_archived_is_inactive",
            ),
            models.CheckConstraint(
                condition=Q(is_archived=True, archived_at__isnull=False)
                | Q(is_archived=False, archived_at__isnull=True),
                name="position_archive_stamp",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.department_id})"


class StaffAssignment(_Tracked):
    """A person holding a position. Current while ``end_date`` is empty."""

    SYNC_POLICY = REFERENCE_READ_ONLY
    RBAC_DEPARTMENT_FIELD = "department_id"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="staff_assignments"
    )
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="assignments")
    # Always the position's department; kept here so department scope and indexes need no join.
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="staff_assignments"
    )
    is_primary = models.BooleanField(default=False)
    reports_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Overrides the reporting line given by the position.",
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="staff_assignment_dates_ordered",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_primary=True, end_date__isnull=True),
                name="staff_one_current_primary_per_user",
            ),
            models.UniqueConstraint(
                fields=["user", "position"],
                condition=Q(end_date__isnull=True),
                name="staff_one_current_assignment_per_position",
            ),
            models.CheckConstraint(
                condition=~Q(reports_to_user=F("user")), name="staff_not_their_own_boss"
            ),
        ]
        indexes = [
            models.Index(fields=["department", "end_date"], name="staff_department_idx"),
            models.Index(fields=["user", "end_date"], name="staff_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} as {self.position_id}"

    @property
    def is_current(self) -> bool:
        return self.end_date is None


class ApprovalHierarchy(_Tracked):
    """One step of a department's approval chain for one kind of request.

    Stored now, consumed by the Approval Centre in Slice 5. ``request_type`` ``DEFAULT``
    is the chain used when no chain exists for a more specific type.
    """

    SYNC_POLICY = ONLINE_ONLY

    class ApproverType(models.TextChoices):
        POSITION = "POSITION", "A position"
        ROLE = "ROLE", "A role"
        DEPARTMENT_HEAD = "DEPARTMENT_HEAD", "The department head"
        REPORTS_TO = "REPORTS_TO", "The requester's line manager"
        USER = "USER", "A named person"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="approval_steps"
    )
    request_type = models.CharField(max_length=40, default=DEFAULT_REQUEST_TYPE)
    step_order = models.PositiveSmallIntegerField()
    approver_type = models.CharField(max_length=20, choices=ApproverType.choices)
    approver_position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approver_role = models.ForeignKey(
        "rbac.Role", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department__name", "request_type", "step_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "request_type", "step_order"],
                name="approval_step_unique",
            ),
            models.CheckConstraint(
                condition=Q(step_order__gte=1), name="approval_step_order_positive"
            ),
            models.CheckConstraint(
                condition=Q(
                    approver_type__in=["POSITION", "ROLE", "DEPARTMENT_HEAD", "REPORTS_TO", "USER"]
                ),
                name="approval_step_type_valid",
            ),
            # Exactly the field that matches the type is filled in; the others are empty.
            models.CheckConstraint(
                condition=(
                    Q(
                        approver_type="POSITION",
                        approver_position__isnull=False,
                        approver_role__isnull=True,
                        approver_user__isnull=True,
                    )
                    | Q(
                        approver_type="ROLE",
                        approver_role__isnull=False,
                        approver_position__isnull=True,
                        approver_user__isnull=True,
                    )
                    | Q(
                        approver_type="USER",
                        approver_user__isnull=False,
                        approver_position__isnull=True,
                        approver_role__isnull=True,
                    )
                    | Q(
                        approver_type__in=["DEPARTMENT_HEAD", "REPORTS_TO"],
                        approver_position__isnull=True,
                        approver_role__isnull=True,
                        approver_user__isnull=True,
                    )
                ),
                name="approval_step_target_matches_type",
            ),
        ]

    def __str__(self):
        return f"{self.department_id} {self.request_type} step {self.step_order}"

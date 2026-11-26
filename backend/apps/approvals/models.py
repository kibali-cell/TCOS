"""Approval Centre data: requests, their append-only history, assignees, notifications and
the TZS limit policy.

Online-only (D-H3): decisions are never made offline. Drafts created offline arrive as drafts
with a caller-supplied id so they cannot be duplicated; official request numbers are given by
the server at submission.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

# Request types. GENERAL and anything an administrator configures follow the department's
# approval chain (Slice 4); the other two are system types with a fixed route (D-065).
GENERAL = "GENERAL"
ROLE_GRANT = "ROLE_GRANT"
TZS_LIMITS_CHANGE = "TZS_LIMITS_CHANGE"
SYSTEM_TYPES = (ROLE_GRANT, TZS_LIMITS_CHANGE)

STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "CANCELLED")
OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW")
FINAL_STATUSES = ("APPROVED", "REJECTED", "CANCELLED")
RISKS = ("LOW", "MEDIUM", "HIGH")
ACTIONS = ("CREATE", "SUBMIT", "REVIEW", "APPROVE", "REJECT", "CANCEL", "COMMENT", "ESCALATE")

# Drafts may be created offline and synced as pending (Slice 9); decisions never.
DRAFTS_SYNCABLE = {
    "offline_read": False,
    "offline_write": True,
    "conflict": "NEVER_LAST_WRITE_WINS",
    "classification": "CONFIDENTIAL",
}
ONLINE_ONLY = {
    "offline_read": False,
    "offline_write": False,
    "conflict": "SERVER_WINS",
    "classification": "CONFIDENTIAL",
}


class RequestSequence(models.Model):
    """Last number issued for a key such as ``REQ-2026``. Row-locked when a number is taken."""

    SYNC_POLICY = ONLINE_ONLY
    key = models.CharField(max_length=20, primary_key=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.key


class ApprovalRequest(models.Model):
    SYNC_POLICY = DRAFTS_SYNCABLE
    RBAC_DEPARTMENT_FIELD = "department_id"
    RBAC_OWNER_FIELDS = ("requester_id",)
    AUDIT_DEPARTMENT_FIELD = "department_id"
    AUDIT_EXCLUDE_FIELDS = ("updated_at",)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    request_type = models.CharField(max_length=40, default=GENERAL)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    department = models.ForeignKey(
        "organisation.Department", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=14, default="DRAFT")
    current_step = models.PositiveSmallIntegerField(default=0)
    # The route fixed at submission, so later hierarchy changes do not alter requests in flight.
    route = models.JSONField(default=list, blank=True)
    amount_tzs = models.BigIntegerField(null=True, blank=True)
    # Set by the server from the active TZS policy; never taken from the client.
    risk_level = models.CharField(max_length=6, default="LOW")
    payload = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.TextField(blank=True)

    local_reference = models.CharField(max_length=60, blank=True)
    created_offline = models.BooleanField(default=False)
    origin_device_id = models.UUIDField(null=True, blank=True)
    client_created_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="request_status_valid"),
            models.CheckConstraint(condition=Q(risk_level__in=RISKS), name="request_risk_valid"),
            models.CheckConstraint(
                condition=Q(amount_tzs__isnull=True) | Q(amount_tzs__gte=0),
                name="request_amount_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["DRAFT", "CANCELLED"]) | Q(request_number__isnull=False),
                name="request_submitted_has_number",
            ),
        ]
        indexes = [
            models.Index(fields=["requester", "status"], name="request_requester_idx"),
            models.Index(fields=["department", "status"], name="request_department_idx"),
            models.Index(fields=["request_type", "status"], name="request_type_idx"),
        ]

    def __str__(self):
        return self.request_number or str(self.id)


class ApprovalAssignee(models.Model):
    """A person who may decide a request at one step. Never the requester."""

    SYNC_POLICY = ONLINE_ONLY
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="assignees")
    step = models.PositiveSmallIntegerField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "user", "step"], name="assignee_unique")
        ]
        indexes = [models.Index(fields=["user", "request"], name="assignee_user_idx")]

    def __str__(self):
        return f"{self.user_id} step {self.step}"


class ApprovalAction(models.Model):
    """One entry in a request's history. Append-only: a database trigger refuses UPDATE and
    DELETE, and refuses a decision made by the request's own requester."""

    SYNC_POLICY = ONLINE_ONLY
    id = models.BigAutoField(primary_key=True)
    request = models.ForeignKey(ApprovalRequest, on_delete=models.PROTECT, related_name="actions")
    action = models.CharField(max_length=10)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    from_status = models.CharField(max_length=14, blank=True)
    to_status = models.CharField(max_length=14)
    step = models.PositiveSmallIntegerField(default=0)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(action__in=ACTIONS), name="action_type_valid"),
            models.CheckConstraint(
                condition=~Q(action="REJECT") | ~Q(comment=""), name="action_reject_has_comment"
            ),
        ]

    def __str__(self):
        return f"{self.action} {self.request_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("The approval history cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("The approval history cannot be deleted.")


class Notification(models.Model):
    """In-app notice. E-mail is not sent unless a mail server is configured (D-070)."""

    SYNC_POLICY = ONLINE_ONLY
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    request = models.ForeignKey(
        ApprovalRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"], name="notification_user_idx")]

    def __str__(self):
        return self.title


class TzsLimitPolicy(models.Model):
    """The TZS risk tiers. One ACTIVE row at a time; every version is kept.

    Changed only by an approved ``TZS_LIMITS_CHANGE`` request. ``is_ratified`` is true once a
    Board Member has approved this version (D-020, D-066).
    """

    SYNC_POLICY = ONLINE_ONLY

    class State(models.TextChoices):
        ACTIVE = "ACTIVE", "In force"
        SUPERSEDED = "SUPERSEDED", "Replaced"
        PROPOSED = "PROPOSED", "Awaiting approval"
        REJECTED = "REJECTED", "Not approved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version_number = models.PositiveIntegerField(unique=True)
    state = models.CharField(max_length=12, choices=State.choices)
    low_max = models.BigIntegerField()
    medium_max = models.BigIntegerField()
    always_high = models.JSONField(default=list)
    reason = models.CharField(max_length=500, blank=True)
    request = models.ForeignKey(
        ApprovalRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_ratified = models.BooleanField(default=False)
    ratified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    ratified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["state"], condition=Q(state="ACTIVE"), name="one_active_tzs_policy"
            ),
            models.CheckConstraint(
                condition=Q(low_max__gte=0) & Q(medium_max__gt=F("low_max")),
                name="tzs_policy_tiers_ordered",
            ),
            models.CheckConstraint(
                condition=Q(is_ratified=False)
                | (Q(ratified_at__isnull=False) & Q(ratified_by__isnull=False)),
                name="tzs_policy_ratified_has_who",
            ),
        ]

    def __str__(self):
        return f"TZS limits v{self.version_number}"

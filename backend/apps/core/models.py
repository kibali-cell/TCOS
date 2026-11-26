"""Core tables shared by every module."""

import uuid

from django.conf import settings
from django.db import models

# What a device may do with each kind of record (enforced from Slice 9).
ONLINE_ONLY = {
    "offline_read": False,
    "offline_write": False,
    "conflict": "SERVER_WINS",
    "classification": "INTERNAL",
}


class ReferenceFigure(models.Model):
    """An initial institutional figure, kept only until real records replace it.

    The dashboard shows these as "reference figures" until live counts exist, and never
    presents one as verified until a person has verified it (CLAUDE.md rule 8).
    """

    SYNC_POLICY = ONLINE_ONLY

    key = models.CharField(max_length=40, primary_key=True)
    label = models.CharField(max_length=100)
    value = models.PositiveIntegerField()
    source_note = models.CharField(max_length=200, default="Initial institutional reference figure")
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}={self.value}"


class Document(models.Model):
    """An uploaded file attached to a record in another module.

    The file itself is in private storage under a random key (never the original name) and is
    reachable only through an authenticated, permission-checked endpoint. Archived, never
    deleted.
    """

    SYNC_POLICY = {
        "offline_read": False,
        "offline_write": False,
        "conflict": "SERVER_WINS",
        "classification": "CONFIDENTIAL",
    }
    RBAC_OWNER_FIELDS = ("uploaded_by_id",)
    AUDIT_EXCLUDE_FIELDS = ("storage_key",)

    class Classification(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        CONFIDENTIAL = "CONFIDENTIAL", "Confidential"
        CHILD_SENSITIVE = "CHILD_SENSITIVE", "Child-sensitive"

    class ScanStatus(models.TextChoices):
        NOT_SCANNED = "NOT_SCANNED", "Not scanned (no scanner configured)"
        CLEAN = "CLEAN", "Scanned, clean"
        INFECTED = "INFECTED", "Infected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The record it belongs to, e.g. "approvals.ApprovalRequest" and its id.
    parent_type = models.CharField(max_length=60)
    parent_id = models.UUIDField()
    original_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=80, unique=True)
    classification = models.CharField(
        max_length=16, choices=Classification.choices, default=Classification.CONFIDENTIAL
    )
    scan_status = models.CharField(
        max_length=12, choices=ScanStatus.choices, default=ScanStatus.NOT_SCANNED
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["uploaded_at"]
        indexes = [models.Index(fields=["parent_type", "parent_id"], name="document_parent_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(size_bytes__gt=0), name="document_not_empty"),
            models.CheckConstraint(
                condition=models.Q(is_archived=False, archived_at__isnull=True)
                | models.Q(is_archived=True, archived_at__isnull=False),
                name="document_archive_stamp",
            ),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.id})"

"""Core tables shared by every module."""

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

import uuid

from django.db import models


class Department(models.Model):
    """A department of the institution.

    Minimal in Slice 2 (department-scoped access needs something to point at).
    Slice 4 adds the hierarchy, heads, positions and staff assignments.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

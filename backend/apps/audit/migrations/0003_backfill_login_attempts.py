"""Turn the sign-in attempts recorded by Slice 1 into audit events.

Each event is marked ``backfilled`` and keeps the original time. Runs once, in time order,
so the hash chain starts with history and continues with new events.
"""

from django.db import migrations
from django.utils import timezone

from apps.audit.hashing import GENESIS, compute_hash


def forwards(apps, schema_editor):
    LoginAttempt = apps.get_model("accounts", "LoginAttempt")
    AuditEvent = apps.get_model("audit", "AuditEvent")
    if AuditEvent.objects.exists():
        return  # never mix into an existing chain

    prev = GENESIS
    for attempt in LoginAttempt.objects.order_by("attempted_at", "id").iterator():
        if attempt.success:
            event_type, success = "LOGIN_SUCCESS", True
        elif attempt.failure_reason == "THROTTLED":
            event_type, success = "LOGIN_BLOCKED", False
        else:
            event_type, success = "LOGIN_FAILED", False
        values = {
            "occurred_at": attempt.attempted_at or timezone.now(),
            "actor_id": attempt.user_id,
            "actor_username": (attempt.username_attempted or "")[:150],
            "event_type": event_type,
            "object_type": "accounts.User" if attempt.user_id else "",
            "object_id": str(attempt.user_id) if attempt.user_id else "",
            "department_id": None,
            "success": success,
            "ip_address": str(attempt.ip_address) if attempt.ip_address else None,
            "user_agent": (attempt.user_agent or "")[:400],
            "request_id": "",
            "changes": {},
            "metadata": {
                "backfilled": True,
                "reason": attempt.failure_reason or "",
            },
        }
        event_hash = compute_hash(prev, values)
        AuditEvent.objects.create(
            occurred_at=values["occurred_at"],
            actor_id=values["actor_id"],
            actor_username=values["actor_username"],
            event_type=event_type,
            object_type=values["object_type"],
            object_id=values["object_id"],
            success=success,
            ip_address=values["ip_address"],
            user_agent=values["user_agent"],
            request_id="",
            changes={},
            metadata=values["metadata"],
            prev_hash=prev,
            event_hash=event_hash,
        )
        prev = event_hash


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_append_only_triggers"),
        ("accounts", "0002_user_department"),
    ]
    # Reverse is a no-op on purpose: the append-only trigger forbids deleting audit rows.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

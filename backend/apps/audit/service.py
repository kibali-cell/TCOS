"""``record()``: the one way to write an audit event.

Call it inside the same ``transaction.atomic()`` block as the change it describes. It
joins that transaction, so the change and its audit event commit together or not at all;
if the audit write fails, the change is rolled back.
"""

from __future__ import annotations

import ipaddress

from django.db import connection, transaction
from django.utils import timezone

from . import context
from .hashing import GENESIS, compute_hash
from .models import AuditEvent
from .sanitise import sanitise

# Serialises audit writes so the hash chain has one strict order. Held until the
# surrounding transaction ends (transaction-level advisory lock).
CHAIN_LOCK_KEY = 7_340_181_221


def _ip(value):
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def record(
    event_type: str,
    *,
    actor=None,
    actor_username: str | None = None,
    object_type: str = "",
    object_id="",
    department_id=None,
    changes=None,
    metadata=None,
    success: bool = True,
) -> AuditEvent:
    ctx = context.current()
    username = actor_username if actor_username is not None else getattr(actor, "username", "")
    values = {
        "occurred_at": timezone.now(),
        "actor_id": getattr(actor, "pk", None),
        "actor_username": (username or "")[:150],
        "event_type": event_type,
        "object_type": (object_type or "")[:100],
        "object_id": str(object_id or "")[:100],
        "department_id": department_id,
        "success": bool(success),
        "ip_address": _ip(ctx.get("ip_address")),
        "user_agent": (ctx.get("user_agent") or "")[:400],
        "request_id": ctx.get("request_id", ""),
        "changes": sanitise(changes),
        "metadata": sanitise(metadata),
    }
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CHAIN_LOCK_KEY])
        previous = AuditEvent.objects.order_by("-id").values_list("event_hash", flat=True).first()
        prev_hash = previous or GENESIS
        event = AuditEvent(
            occurred_at=values["occurred_at"],
            actor_id=values["actor_id"],
            actor_username=values["actor_username"],
            event_type=values["event_type"],
            object_type=values["object_type"],
            object_id=values["object_id"],
            department_id=values["department_id"],
            changes=values["changes"],
            metadata=values["metadata"],
            success=values["success"],
            ip_address=values["ip_address"],
            user_agent=values["user_agent"],
            request_id=values["request_id"],
            prev_hash=prev_hash,
            event_hash=compute_hash(prev_hash, values),
        )
        event._from_service = True
        event.save()
    return event


def verify_chain(*, batch: int = 2000) -> dict:
    """Recompute every hash in order. Returns ``{"ok", "checked", "head", "broken_at"}``."""
    prev = GENESIS
    checked = 0
    last_id = 0
    while True:
        rows = list(AuditEvent.objects.filter(id__gt=last_id).order_by("id")[:batch])
        if not rows:
            break
        for row in rows:
            values = {
                "occurred_at": row.occurred_at,
                "actor_id": row.actor_id,
                "actor_username": row.actor_username,
                "event_type": row.event_type,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "department_id": row.department_id,
                "success": row.success,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "request_id": row.request_id,
                "changes": row.changes,
                "metadata": row.metadata,
            }
            if row.prev_hash != prev or row.event_hash != compute_hash(prev, values):
                return {"ok": False, "checked": checked, "head": prev, "broken_at": row.id}
            prev = row.event_hash
            checked += 1
            last_id = row.id
    return {"ok": True, "checked": checked, "head": prev, "broken_at": None}

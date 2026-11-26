"""Tamper-evident hash chain.

Each event stores the hash of the previous event and its own hash over its content, so
editing or removing an old event breaks every hash after it. This detects tampering by
anyone who cannot rewrite the whole chain. It does not stop a database superuser who
rewrites everything, so also keep the head hash (``manage.py verify_audit_chain``) and
off-site backups somewhere the same person cannot reach.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

GENESIS = "0" * 64
FIELDS = (
    "occurred_at",
    "actor_id",
    "actor_username",
    "event_type",
    "object_type",
    "object_id",
    "department_id",
    "success",
    "ip_address",
    "user_agent",
    "request_id",
    "changes",
    "metadata",
)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _text(value):
    """Stable form of a value for hashing (the same on insert and on later verification)."""
    if value is None or isinstance(value, (dict, list, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    return str(value)


def compute_hash(prev_hash: str, values: dict) -> str:
    payload = {name: _text(values.get(name)) for name in FIELDS}
    digest = hashlib.sha256()
    digest.update(prev_hash.encode())
    digest.update(b"|")
    digest.update(canonical(payload).encode())
    return digest.hexdigest()

"""Per-request context (request id, IP, user agent) for audit entries."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_context: ContextVar[dict | None] = ContextVar("audit_context", default=None)
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def current() -> dict:
    return _context.get() or {}


def set_context(value: dict | None):
    return _context.set(value)


def reset_context(token) -> None:
    _context.reset(token)


def new_request_id(incoming: str | None) -> str:
    """Use a caller-supplied id only if it is plain and short, otherwise make one."""
    if incoming and _VALID_REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex

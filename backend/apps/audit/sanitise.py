"""Keep secrets and sensitive values out of audit entries.

Applied to every ``changes`` and ``metadata`` value before it is stored, whatever the caller
passes. A field whose NAME looks secret is replaced by a marker; the value is never kept.
"""

from __future__ import annotations

import json
import re

from django.core.serializers.json import DjangoJSONEncoder

SECRET_NAME = re.compile(
    r"pass(word|phrase)|secret|token|session_?key|csrf|otp|recovery|api_?key|authorization"
    r"|credential|private_?key|^hash$|_hash$|signature",
    re.IGNORECASE,
)
REDACTED = "[redacted]"
MAX_TEXT = 2000
MAX_DEPTH = 6


def _clean(value, depth: int):
    if depth > MAX_DEPTH:
        return "[too deep]"
    if isinstance(value, dict):
        return {
            str(key)[:100]: (REDACTED if SECRET_NAME.search(str(key)) else _clean(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(item, depth + 1) for item in list(value)[:200]]
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + "…"
    return value


def sanitise(value):
    """Return a JSON-safe copy of ``value`` with secrets removed and sizes limited."""
    if value is None:
        return {}
    # Round-trip so dates, UUIDs and decimals become plain text, exactly as they will be
    # stored; the hash is computed over this form.
    plain = json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))
    return _clean(plain, 0)

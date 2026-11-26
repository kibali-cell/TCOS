"""Generic hook: audit create, modify and archive for any model that opts in.

A model opts in by being changed only through service functions that call these helpers,
inside the same transaction as the change::

    before = snapshot(record)
    record.title = "New"
    record.save()
    record_updated(actor, record, before)

Sensitive fields are never stored. Names that look secret are removed automatically
(see ``sanitise``); a model can list more in ``AUDIT_EXCLUDE_FIELDS``.
"""

from __future__ import annotations

from . import events
from .service import record as write_event


def _excluded(instance) -> set[str]:
    return set(getattr(type(instance), "AUDIT_EXCLUDE_FIELDS", ()))


def snapshot(instance) -> dict:
    """Plain copy of the concrete field values (foreign keys as ids)."""
    excluded = _excluded(instance)
    values = {}
    for field in instance._meta.concrete_fields:
        if field.attname in excluded or field.name in excluded:
            continue
        values[field.attname] = getattr(instance, field.attname)
    return values


def diff(before: dict, after: dict) -> dict:
    """{field: {"from": old, "to": new}} for fields that differ."""
    return {
        name: {"from": before.get(name), "to": after.get(name)}
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }


def _object_fields(instance) -> dict:
    return {
        "object_type": instance._meta.label,
        "object_id": instance.pk,
        "department_id": getattr(
            instance, getattr(type(instance), "AUDIT_DEPARTMENT_FIELD", "department_id"), None
        ),
    }


def record_created(actor, instance, **extra):
    after = snapshot(instance)
    return write_event(
        events.RECORD_CREATED,
        actor=actor,
        changes={name: {"from": None, "to": value} for name, value in after.items()},
        **_object_fields(instance),
        **extra,
    )


def record_updated(actor, instance, before: dict, **extra):
    """Writes nothing if nothing changed. Returns the event or None."""
    changes = diff(before, snapshot(instance))
    if not changes:
        return None
    return write_event(
        events.RECORD_UPDATED, actor=actor, changes=changes, **_object_fields(instance), **extra
    )


def record_archived(actor, instance, **extra):
    return write_event(events.RECORD_ARCHIVED, actor=actor, **_object_fields(instance), **extra)


def record_deleted(actor, instance, **extra):
    """Hard deletion needs an explicit permission and is always audited. Call before deleting."""
    return write_event(
        events.RECORD_DELETED,
        actor=actor,
        changes={name: {"from": value, "to": None} for name, value in snapshot(instance).items()},
        **_object_fields(instance),
        **extra,
    )

"""Query-string filters for the audit viewer and the export."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import AuditEvent


def _day(value: str, field: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError({field: ["Use the format YYYY-MM-DD."]}) from exc
    return timezone.make_aware(datetime.combine(parsed, time.min))  # local (Dar es Salaam) day


def apply_filters(queryset, params):
    """Narrow ``queryset`` by the supplied parameters. Unknown parameters are ignored."""
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(
            Q(actor_username__icontains=text)
            | Q(event_type__icontains=text)
            | Q(object_type__icontains=text)
            | Q(object_id__icontains=text)
            | Q(request_id__icontains=text)
        )
    if params.get("actor"):
        queryset = queryset.filter(actor_username__icontains=params["actor"].strip())
    if params.get("actor_id"):
        try:
            queryset = queryset.filter(actor_id=params["actor_id"])
        except (ValueError, TypeError, Exception) as exc:  # invalid uuid
            raise ValidationError({"actor_id": ["Not a valid id."]}) from exc
    types = [t.strip().upper() for t in (params.get("event_type") or "").split(",") if t.strip()]
    if types:
        queryset = queryset.filter(event_type__in=types)
    if params.get("object_type"):
        queryset = queryset.filter(object_type=params["object_type"].strip())
    if params.get("object_id"):
        queryset = queryset.filter(object_id=params["object_id"].strip())
    if params.get("request_id"):
        queryset = queryset.filter(request_id=params["request_id"].strip())
    outcome = (params.get("success") or "").lower()
    if outcome in ("true", "1", "yes"):
        queryset = queryset.filter(success=True)
    elif outcome in ("false", "0", "no"):
        queryset = queryset.filter(success=False)
    elif outcome:
        raise ValidationError({"success": ["Use true or false."]})
    if params.get("date_from"):
        queryset = queryset.filter(occurred_at__gte=_day(params["date_from"], "date_from"))
    if params.get("date_to"):  # inclusive of the whole day
        queryset = queryset.filter(
            occurred_at__lt=_day(params["date_to"], "date_to") + timedelta(days=1)
        )
    return queryset


FILTER_NAMES = (
    "q",
    "actor",
    "actor_id",
    "event_type",
    "object_type",
    "object_id",
    "request_id",
    "success",
    "date_from",
    "date_to",
)


def clean_filters(params) -> dict:
    """Only the known filter names, as plain text (what gets stored on an export event)."""
    return {name: str(params[name]) for name in FILTER_NAMES if params.get(name)}


__all__ = ["AuditEvent", "FILTER_NAMES", "apply_filters", "clean_filters"]

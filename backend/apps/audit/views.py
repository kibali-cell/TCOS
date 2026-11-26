"""Read-only audit viewer. There are no endpoints that change or delete an event."""

import csv
import io
import json

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import StandardPagination
from apps.rbac.permissions import RBACPermission, filter_queryset, request_access

from . import events
from .filters import apply_filters, clean_filters
from .models import AuditEvent
from .service import record

EXPORT_LIMIT = 50_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _scoped(request, action="VIEW"):
    return filter_queryset(
        request.user, "audit", action, AuditEvent.objects.all(), access=request_access(request)
    )


def summary(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_username": event.actor_username,
        "event_type": event.event_type,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "success": event.success,
        "ip_address": event.ip_address,
        "request_id": event.request_id,
    }


def detail(event: AuditEvent) -> dict:
    return {
        **summary(event),
        "user_agent": event.user_agent,
        "changes": event.changes,
        "metadata": event.metadata,
        "department_id": str(event.department_id) if event.department_id else None,
        "prev_hash": event.prev_hash,
        "event_hash": event.event_hash,
    }


class _AuditView(APIView):
    permission_classes = [RBACPermission]
    rbac_module = "audit"
    rbac_actions = {"get": "VIEW", "post": "EXPORT"}


class EventListView(_AuditView):
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        queryset = apply_filters(_scoped(request), request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([summary(event) for event in page])


class EventDetailView(_AuditView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk):
        return Response(detail(get_object_or_404(_scoped(request), pk=pk)))


class EventTypesView(_AuditView):
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        return Response({"results": list(events.EVENT_TYPES)})


def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


class ExportView(_AuditView):
    """CSV export of the filtered events. Needs audit.EXPORT and is itself audited."""

    http_method_names = ["post", "options"]

    def post(self, request):
        filters = clean_filters(request.data if hasattr(request.data, "get") else {})
        queryset = apply_filters(_scoped(request, "EXPORT"), filters)
        count = queryset.count()
        if count > EXPORT_LIMIT:
            raise ValidationError(
                {
                    "detail": [
                        f"{count} events match. Narrow the filters to {EXPORT_LIMIT} or fewer."
                    ]
                }
            )
        rows = list(queryset.order_by("id"))
        with transaction.atomic():
            # The export is recorded before any data leaves, in the same transaction.
            record(
                events.DATA_EXPORTED,
                actor=request.user,
                object_type="audit.AuditEvent",
                metadata={"filters": filters, "rows": len(rows), "format": "csv"},
            )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "time",
                "actor",
                "event",
                "object_type",
                "object_id",
                "success",
                "ip",
                "request_id",
                "changes",
                "details",
            ]
        )
        for event in rows:
            writer.writerow(
                [
                    event.id,
                    event.occurred_at.astimezone(timezone.get_current_timezone()).isoformat(
                        timespec="seconds"
                    ),
                    _safe_cell(event.actor_username),
                    event.event_type,
                    event.object_type,
                    _safe_cell(event.object_id),
                    "yes" if event.success else "no",
                    event.ip_address or "",
                    event.request_id,
                    _safe_cell(json.dumps(event.changes, ensure_ascii=False, sort_keys=True)),
                    _safe_cell(json.dumps(event.metadata, ensure_ascii=False, sort_keys=True)),
                ]
            )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="tcos-audit-log.csv"'
        response["Cache-Control"] = "no-store"
        return response

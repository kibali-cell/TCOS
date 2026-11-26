"""Dashboard numbers. Everything here is read from the database.

* Institution-wide figures need the module's VIEW permission at ALL scope; without it the
  figure is simply not in the response (enforced here, not in the screen).
* Each number says where it came from: ``live`` (counted from records), ``reference`` (an
  initial institutional figure, never verified unless a person did so) or ``none`` (no
  records and no reference exist yet). Nothing is invented (CLAUDE.md rule 8).
"""

from __future__ import annotations

from apps.approvals import services as approval_services
from apps.approvals.models import OPEN_STATUSES, ApprovalRequest, Notification
from apps.audit.models import AuditEvent
from apps.core.models import ReferenceFigure
from apps.organisation.models import StaffAssignment
from apps.rbac.permissions import effective_permissions, filter_queryset

REFERENCE_LABEL = "Reference figure (not yet verified)"
VERIFIED_LABEL = "Reference figure (verified)"


def _everything(access, module, action="VIEW") -> bool:
    granted = access.get((module, action))
    return bool(granted and granted.everything)


def _metric(key, label, live=None, references=None, note=""):
    """One number with its source. ``live`` is None when it cannot be counted yet."""
    ref = (references or {}).get(key)
    if live:  # records exist: use the count, and keep the reference figure for context
        return {
            "key": key,
            "label": label,
            "value": live,
            "source": "live",
            "source_label": "Live count from records",
            "reference_value": ref.value if ref else None,
            "is_verified": True,
            "note": note,
        }
    if ref:
        return {
            "key": key,
            "label": label,
            "value": ref.value,
            "source": "reference",
            "source_label": VERIFIED_LABEL if ref.is_verified else REFERENCE_LABEL,
            "reference_value": ref.value,
            "is_verified": ref.is_verified,
            "note": note or "No records have been entered yet.",
        }
    return {
        "key": key,
        "label": label,
        "value": None,
        "source": "none",
        "source_label": "No data yet",
        "reference_value": None,
        "is_verified": False,
        "note": note or "No records have been entered yet.",
    }


def _event(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "actor": event.actor_username or "system",
        "event_type": event.event_type,
        "object_type": event.object_type,
        "success": event.success,
    }


def _recent_activity(user, access, department_id=None, limit=10):
    if not access.get(("audit", "VIEW")):
        return None
    queryset = filter_queryset(user, "audit", "VIEW", AuditEvent.objects.all(), access=access)
    if department_id:
        queryset = queryset.filter(department_id=department_id)
    return [_event(e) for e in queryset.order_by("-id")[:limit]]


def _notifications(user):
    rows = Notification.objects.filter(user=user)
    return {
        "unread": rows.filter(read_at__isnull=True).count(),
        "latest": [
            {
                "id": str(n.pk),
                "title": n.title,
                "body": n.body,
                "request_id": str(n.request_id) if n.request_id else None,
                "created_at": n.created_at,
                "is_read": n.read_at is not None,
            }
            for n in rows.order_by("-created_at")[:5]
        ],
    }


def build_dashboard(user) -> dict:
    access = effective_permissions(user)
    references = {r.key: r for r in ReferenceFigure.objects.all()}
    figures = []

    if _everything(access, "children"):
        # No children module yet (Phase Two), so these can only be reference figures.
        figures += [
            _metric("total_children", "Total children", None, references),
            _metric("residential_children", "Children in residential care", None, references),
            _metric("outreach_children", "Children in outreach", None, references),
        ]
    if _everything(access, "hr"):
        employees = (
            StaffAssignment.objects.filter(end_date__isnull=True, user__status="ACTIVE")
            .values("user_id")
            .distinct()
            .count()
        )
        figures.append(
            _metric(
                "total_employees",
                "Employees",
                employees,
                references,
                note="Counted from current staff assignments.",
            )
        )
    if _everything(access, "projects"):
        figures.append(
            _metric("active_projects", "Active projects", None, None, "No projects module yet.")
        )

    approvals = None
    if access.get(("approvals", "VIEW")):
        visible = filter_queryset(
            user, "approvals", "VIEW", ApprovalRequest.objects.all(), access=access
        )
        approvals = {
            "waiting_for_me": approval_services.pending_for(user).count(),
            "open_in_my_scope": visible.filter(status__in=OPEN_STATUSES).count(),
            "mine_open": ApprovalRequest.objects.filter(
                requester=user, status__in=OPEN_STATUSES
            ).count(),
        }

    finance = None
    if _everything(access, "finance"):
        finance = {
            "figures": [],
            "note": "No financial records have been entered yet, so there is nothing to total.",
        }

    return {
        "figures": figures,
        "approvals": approvals,
        "finance": finance,
        "recent_activity": _recent_activity(user, access),
        "notifications": _notifications(user),
        "department": (
            {"id": str(user.department_id), "name": user.department.name}
            if user.department_id
            else None
        ),
    }


def can_see_department(user, access, department) -> bool:
    if _everything(access, "administration") or _everything(access, "approvals"):
        return True
    if user.department_id == department.pk:
        return True
    for module in ("approvals", "administration", "users"):
        granted = access.get((module, "VIEW"))
        if granted and department.pk in granted.departments:
            return True
    return False


def build_department_dashboard(user, department) -> dict:
    access = effective_permissions(user)
    open_requests = ApprovalRequest.objects.filter(
        department=department, status__in=OPEN_STATUSES
    ).select_related("requester")
    staff = (
        StaffAssignment.objects.filter(
            department=department, end_date__isnull=True, user__status="ACTIVE"
        )
        .values("user_id")
        .distinct()
        .count()
    )
    pending = None
    if access.get(("approvals", "VIEW")) or user.department_id == department.pk:
        pending = {
            "count": open_requests.count(),
            "latest": [
                {
                    "id": str(r.pk),
                    "request_number": r.request_number,
                    "title": r.title,
                    "status": r.status,
                    "requester": r.requester.full_name,
                    "submitted_at": r.submitted_at,
                }
                for r in open_requests.order_by("-submitted_at")[:10]
            ],
        }
    return {
        "department": {
            "id": str(department.pk),
            "name": department.name,
            "head": department.head.full_name if department.head_id else None,
        },
        "staff_count": staff,
        "pending_approvals": pending,
        "recent_activity": _recent_activity(user, access, department_id=department.pk),
    }

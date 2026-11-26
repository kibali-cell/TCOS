"""Approval Centre: every change to a request goes through here.

Rules (CLAUDE.md rules 6, 11, 14; D-065 to D-069):

* **The server decides.** Approvers, the request number, the risk level and every status
  change are decided here. Whatever a client sends about them is ignored.
* **Nobody decides their own request.** Refused before anything else is looked at, and
  again by a database trigger on the history table. Refusals are audited.
* **A second person for sensitive power.** Role grants and changes to TZS limits are
  system request types with a fixed route (Executive Director or Board Member, never the
  requester, never the person receiving the role).
* **One transaction per step.** The status change, the history row, the notifications and
  the audit event commit together or not at all.
"""

from __future__ import annotations

import functools
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.audit import events as audit_events
from apps.audit.service import record as audit
from apps.organisation.models import DEFAULT_REQUEST_TYPE, ApprovalHierarchy, Department
from apps.rbac import services as rbac_services
from apps.rbac.models import Role, UserRole
from apps.rbac.permissions import can, filter_queryset

from . import limits
from .models import (
    GENERAL,
    OPEN_STATUSES,
    ROLE_GRANT,
    TZS_LIMITS_CHANGE,
    ApprovalAction,
    ApprovalAssignee,
    ApprovalRequest,
    Notification,
    RequestSequence,
    TzsLimitPolicy,
)

OBJECT_TYPE = "approvals.ApprovalRequest"
ED = "EXECUTIVE_DIRECTOR"
BOARD = "BOARD_MEMBER"
# Granting any of these is approved by a Board Member only, never by the Executive Director.
TOP_ROLES = {"ADMINISTRATOR", ED, BOARD}
MAX_AMOUNT = 10**13


class StateConflict(APIException):
    status_code = 409
    default_code = "invalid_state"
    default_detail = "This request is not in a state that allows that."


def _forbid(message, code):
    raise PermissionDenied(message, code)


def _invalid(field, message):
    raise ValidationError({field: [message]})


# --- Notifications ---------------------------------------------------------------------


def notify(users, title, body="", request=None):
    seen = set()
    rows = []
    for user in users:
        if user.pk in seen:
            continue
        seen.add(user.pk)
        rows.append(Notification(user=user, title=title[:200], body=body[:500], request=request))
    Notification.objects.bulk_create(rows)


# --- Numbers -----------------------------------------------------------------------------


def next_request_number(now=None) -> str:
    """TCOS-REQ-YYYY-NNNNNN, issued under a row lock so parallel submits never collide.

    A number is issued only when a request is submitted and is never handed out twice,
    even if the submit later fails (the gap is harmless; a duplicate would not be).
    """
    year = (now or timezone.now()).year
    key = f"REQ-{year}"
    RequestSequence.objects.bulk_create([RequestSequence(key=key)], ignore_conflicts=True)
    row = RequestSequence.objects.select_for_update().get(key=key)
    row.last_value += 1
    row.save(update_fields=["last_value"])
    return f"TCOS-{key}-{row.last_value:06d}"


# --- Who may decide --------------------------------------------------------------------


def _role_holders(codes, department=None):
    today = timezone.localdate()
    rows = (
        UserRole.objects.filter(
            role__code__in=codes,
            role__is_active=True,
            revoked_at__isnull=True,
            user__status="ACTIVE",
        )
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .select_related("user")
    )
    return [row.user for row in rows]


def _holders_of_role_id(role_id):
    code = Role.objects.filter(pk=role_id).values_list("code", flat=True).first()
    return _role_holders([code]) if code else []


def _line_manager_users(requester):
    assignment = (
        requester.staff_assignments.filter(end_date__isnull=True)
        .order_by("-is_primary", "-start_date")
        .select_related("position")
        .first()
    )
    if assignment is None:
        return []
    if assignment.reports_to_user_id:
        return [assignment.reports_to_user]
    boss = assignment.position.reports_to
    if boss is None:
        return []
    from apps.organisation.models import StaffAssignment

    return [
        a.user
        for a in StaffAssignment.objects.filter(
            position=boss, end_date__isnull=True
        ).select_related("user")
    ]


def _candidates(descriptor, request: ApprovalRequest):
    kind = descriptor["type"]
    if kind == "ROLES":
        return _role_holders(descriptor["role_codes"])
    if kind == "ROLE":
        return _holders_of_role_id(descriptor["role_id"])
    if kind == "POSITION":
        from apps.organisation.models import StaffAssignment

        return [
            a.user
            for a in StaffAssignment.objects.filter(
                position_id=descriptor["position_id"], end_date__isnull=True
            ).select_related("user")
        ]
    if kind == "USER":
        return list(User.objects.filter(pk=descriptor["user_id"]))
    if kind == "DEPARTMENT_HEAD":
        head = request.department.head if request.department_id else None
        return [head] if head else []
    if kind == "REPORTS_TO":
        return _line_manager_users(request.requester)
    return []


def _excluded_ids(request: ApprovalRequest, extra=()) -> set:
    excluded = {request.requester_id, *extra}
    grantee = request.payload.get("user_id") if request.request_type == ROLE_GRANT else None
    if grantee:
        excluded.add(_uuid(grantee))
    return excluded


def _uuid(value):
    import uuid

    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _eligible(descriptor, request, extra_excluded=()):
    excluded = _excluded_ids(request, extra_excluded)
    people = {}
    for user in _candidates(descriptor, request):
        if user.pk in excluded or user.status != "ACTIVE":
            continue
        if not can(user, "approvals", "APPROVE"):
            continue
        people[user.pk] = user
    return list(people.values())


ESCALATION_LADDER = (
    {"type": "ROLES", "role_codes": [ED], "label": "Executive Director"},
    {"type": "ROLES", "role_codes": [BOARD], "label": "Board Member"},
)


def _resolve_step(request, entry, extra_excluded=()):
    """People who may decide this route entry. Escalates when nobody else can (D-068).

    Returns (people, escalation_label or None). Fixed system routes never escalate.
    """
    people = _eligible(entry, request, extra_excluded)
    if people or entry.get("no_escalation"):
        return people, None
    for rung in ESCALATION_LADDER:
        people = _eligible(rung, request, extra_excluded)
        if people:
            return people, rung["label"]
    return [], None


def _describe(step: ApprovalHierarchy) -> dict:
    kind = step.approver_type
    entry = {"type": kind, "order": step.step_order}
    if kind == "POSITION":
        entry.update(position_id=str(step.approver_position_id))
        entry["label"] = f"Position: {step.approver_position.title}"
    elif kind == "ROLE":
        entry.update(role_id=str(step.approver_role_id))
        entry["label"] = f"Role: {step.approver_role.name}"
    elif kind == "USER":
        entry.update(user_id=str(step.approver_user_id))
        entry["label"] = f"Person: {step.approver_user.full_name}"
    elif kind == "DEPARTMENT_HEAD":
        entry["label"] = "Head of the department"
    else:
        entry["label"] = "The requester's line manager"
    return entry


def build_route(request: ApprovalRequest) -> list[dict]:
    """The approval route, frozen onto the request when it is submitted."""
    if request.request_type == ROLE_GRANT:
        role = Role.objects.get(pk=request.payload["role_id"])
        codes = [BOARD] if role.code in TOP_ROLES else [ED, BOARD]
        label = "Board Member" if codes == [BOARD] else "Executive Director or Board Member"
        return [
            {
                "type": "ROLES",
                "role_codes": codes,
                "order": 1,
                "label": label,
                "source": "SYSTEM",
                "no_escalation": True,
            }
        ]
    if request.request_type == TZS_LIMITS_CHANGE:
        return [
            {
                "type": "ROLES",
                "role_codes": [ED, BOARD],
                "order": 1,
                "label": "Executive Director or Board Member",
                "source": "SYSTEM",
                "no_escalation": True,
            }
        ]
    steps = []
    if request.department_id:
        for kind in (request.request_type, DEFAULT_REQUEST_TYPE):
            found = (
                ApprovalHierarchy.objects.filter(
                    department=request.department, request_type=kind, is_active=True
                )
                .select_related("approver_position", "approver_role", "approver_user")
                .order_by("step_order")
            )
            steps = [_describe(step) | {"source": "CHAIN"} for step in found]
            if steps:
                break
    if not steps:
        steps = [
            {
                "type": "ROLES",
                "role_codes": [ED],
                "label": "Executive Director (no approval route is set for this department)",
                "source": "FALLBACK",
            }
        ]
    for number, entry in enumerate(steps, start=1):
        entry["order"] = number
    return steps


def _set_assignees(request, step_number, people):
    request.assignees.all().delete()
    ApprovalAssignee.objects.bulk_create(
        [ApprovalAssignee(request=request, user=u, step=step_number) for u in people]
    )


def _no_approver(entry):
    raise ValidationError(
        {
            "detail": [
                f"Nobody is available to approve this ({entry['label']}). Nobody can approve "
                "their own request, so another approver is needed. Ask an administrator to "
                "check the approval route and who holds the approving roles."
            ]
        }
    )


# --- Request lifecycle -----------------------------------------------------------------


def _locked(request_id) -> ApprovalRequest:
    try:
        return ApprovalRequest.objects.select_for_update().get(pk=request_id)
    except ApprovalRequest.DoesNotExist:
        from django.http import Http404

        raise Http404 from None


def _log(request, action, actor, from_status, comment="", step=None):
    return ApprovalAction.objects.create(
        request=request,
        action=action,
        actor=actor,
        from_status=from_status,
        to_status=request.status,
        step=request.current_step if step is None else step,
        comment=comment,
    )


def _audit(event, actor, request, from_status, extra=None, success=True):
    audit(
        event,
        actor=actor,
        object_type=OBJECT_TYPE,
        object_id=request.pk,
        department_id=request.department_id,
        changes={"status": {"from": from_status, "to": request.status}},
        metadata={
            "request_number": request.request_number,
            "request_type": request.request_type,
            "risk_level": request.risk_level,
            "step": request.current_step,
            **(extra or {}),
        },
        success=success,
    )


def _touch(request):
    request.version += 1
    request.save()


def _clean_amount(value):
    if value in (None, ""):
        return None
    try:
        amount = int(value)
    except (TypeError, ValueError):
        _invalid("amount_tzs", "Enter a whole number of shillings.")
    if amount < 0 or amount > MAX_AMOUNT:
        _invalid("amount_tzs", "Enter an amount of zero or more.")
    return amount


def _clean_content(data: dict) -> dict:
    title = (data.get("title") or "").strip()
    if not title:
        _invalid("title", "Give the request a title.")
    kind = (data.get("kind") or "").strip()
    if kind and kind not in limits.ALWAYS_HIGH_KINDS:
        _invalid("kind", "Choose one of the listed kinds, or leave it empty.")
    return {
        "title": title[:200],
        "description": (data.get("description") or "").strip(),
        "amount_tzs": _clean_amount(data.get("amount_tzs")),
        "kind": kind,
    }


def _own_draft(actor, request):
    if request.requester_id != actor.pk:
        _forbid("Only the person who raised a request can do that.", "not_requester")
    if request.status != "DRAFT":
        raise StateConflict("Only a draft can be edited.")


@transaction.atomic
def create_draft(actor, data: dict, *, request_id=None):
    """Create a draft. Idempotent on ``request_id`` so a repeated upload adds nothing."""
    if request_id is not None:
        existing = ApprovalRequest.objects.filter(pk=request_id).first()
        if existing is not None:
            if existing.requester_id != actor.pk:
                raise StateConflict("That id is already in use.")
            return existing, False
    content = _clean_content(data)
    if actor.department_id is None:
        raise ValidationError(
            {"detail": ["You are not placed in a department yet. Ask an administrator."]}
        )
    request = ApprovalRequest(
        requester=actor,
        department_id=actor.department_id,
        title=content["title"],
        description=content["description"],
        amount_tzs=content["amount_tzs"],
        payload={"kind": content["kind"]},
        local_reference=(data.get("local_reference") or "")[:60],
        created_offline=bool(data.get("created_offline")),
        origin_device_id=data.get("origin_device_id"),
        client_created_at=data.get("client_created_at"),
    )
    if request_id is not None:
        request.pk = request_id
    request.save()
    _log(request, "CREATE", actor, "", step=0)
    _audit(audit_events.APPROVAL_CREATED, actor, request, "")
    return request, True


@transaction.atomic
def update_draft(actor, request_id, data: dict) -> ApprovalRequest:
    request = _locked(request_id)
    _own_draft(actor, request)
    content = _clean_content(data)
    request.title = content["title"]
    request.description = content["description"]
    request.amount_tzs = content["amount_tzs"]
    request.payload = {**request.payload, "kind": content["kind"]}
    _touch(request)
    return request


def _submit_locked(actor, request):
    from_status = request.status
    request.request_number = next_request_number()
    policy = limits.active_policy()
    if request.request_type == GENERAL:
        request.risk_level = limits.risk_for(
            request.amount_tzs, request.payload.get("kind", ""), policy
        )
        request.payload = {
            **request.payload,
            "tzs_policy_version": policy.version_number if policy else 0,
        }
    else:
        request.risk_level = "HIGH"  # sensitive system requests are always HIGH
    route = build_route(request)
    for entry in route:  # every step must be decidable by someone, or it cannot be submitted
        people, _ = _resolve_step(request, entry)
        if not people:
            _no_approver(entry)
    people, escalated = _resolve_step(request, route[0])
    request.route = route
    request.status = "SUBMITTED"
    request.current_step = 1
    request.submitted_at = timezone.now()
    _touch(request)
    _set_assignees(request, 1, people)
    _log(request, "SUBMIT", actor, from_status)
    _audit(audit_events.APPROVAL_SUBMITTED, actor, request, from_status)
    if escalated:
        _record_escalation(request, actor, route[0], escalated)
    notify(
        people,
        f"{request.request_number} needs your decision",
        f"{request.title} ({request.risk_level} risk)",
        request,
    )


def _record_escalation(request, actor, entry, label):
    request.route[entry["order"] - 1]["escalated_to"] = label
    request.save(update_fields=["route"])
    _log(
        request,
        "ESCALATE",
        actor,
        request.status,
        f"Nobody else could approve step {entry['order']} ({entry['label']}), "
        f"so it went to the {label}.",
    )
    _audit(audit_events.APPROVAL_ESCALATED, actor, request, request.status, {"to": label})


@transaction.atomic
def submit(actor, request_id) -> ApprovalRequest:
    request = _locked(request_id)
    _own_draft(actor, request)
    if request.request_type != GENERAL:
        raise StateConflict("This request is raised through its own form.")
    _clean_content({"title": request.title, "kind": request.payload.get("kind", "")})
    _submit_locked(actor, request)
    return request


def _refusable(function):
    """Audit a refused decision (outside the rolled-back transaction), then re-raise."""

    @functools.wraps(function)
    def wrapper(actor, request_id, *args, **kwargs):
        try:
            return function(actor, request_id, *args, **kwargs)
        except PermissionDenied as error:
            request = ApprovalRequest.objects.filter(pk=request_id).first()
            if request is not None:
                with transaction.atomic():
                    audit(
                        audit_events.APPROVAL_REFUSED,
                        actor=actor,
                        object_type=OBJECT_TYPE,
                        object_id=request.pk,
                        department_id=request.department_id,
                        metadata={
                            "request_number": request.request_number,
                            "attempt": function.__name__,
                            "reason": str(error.detail),
                            "code": error.get_codes(),
                        },
                        success=False,
                    )
            raise

    return wrapper


def _check_may_decide(actor, request, action_name):
    if request.requester_id == actor.pk:
        _forbid("You cannot review, approve or reject your own request.", "self_decision")
    if request.status not in OPEN_STATUSES:
        raise StateConflict("This request is no longer waiting for a decision.")
    if not request.assignees.filter(user=actor, step=request.current_step).exists():
        _forbid("This request is not waiting for your decision.", "not_assigned")
    needed = "APPROVE" if action_name == "REVIEW" else action_name
    if not can(actor, "approvals", needed):
        _forbid("You do not have permission to do that.", "permission_denied")


def _reauthenticate(actor, request, password):
    """HIGH-risk decisions need the approver's password again (D-H4)."""
    if request.risk_level != "HIGH":
        return
    if not password or not actor.check_password(password):
        raise ValidationError(
            {"password": ["Enter your password to confirm this high-risk decision."]}
        )


@_refusable
@transaction.atomic
def review(actor, request_id, comment="") -> ApprovalRequest:
    request = _locked(request_id)
    _check_may_decide(actor, request, "REVIEW")
    if request.status != "SUBMITTED":
        raise StateConflict("This request is already under review.")
    from_status = request.status
    request.status = "UNDER_REVIEW"
    _touch(request)
    _log(request, "REVIEW", actor, from_status, comment or "")
    _audit(audit_events.APPROVAL_REVIEWED, actor, request, from_status)
    notify(
        [request.requester], f"{request.request_number} is being reviewed", request.title, request
    )
    return request


@_refusable
@transaction.atomic
def approve(actor, request_id, comment="", password=None) -> ApprovalRequest:
    request = _locked(request_id)
    _check_may_decide(actor, request, "APPROVE")
    _reauthenticate(actor, request, password)
    from_status = request.status
    decided_step = request.current_step
    approvers_so_far = set(
        request.actions.filter(action="APPROVE").values_list("actor_id", flat=True)
    ) | {actor.pk}
    if decided_step < len(request.route):
        entry = request.route[decided_step]
        people, escalated = _resolve_step(request, entry, approvers_so_far)
        if not people:
            _no_approver(entry)
        request.current_step = decided_step + 1
        request.status = "UNDER_REVIEW"
        _touch(request)
        _set_assignees(request, request.current_step, people)
        _log(request, "APPROVE", actor, from_status, comment or "", step=decided_step)
        _audit(
            audit_events.APPROVAL_DECISION,
            actor,
            request,
            from_status,
            {"decision": "APPROVED_STEP", "decided_step": decided_step},
        )
        if escalated:
            _record_escalation(request, actor, entry, escalated)
        notify(people, f"{request.request_number} needs your decision", request.title, request)
        notify(
            [request.requester],
            f"{request.request_number} passed step {decided_step}",
            f"It now waits for step {request.current_step}.",
            request,
        )
        return request
    request.status = "APPROVED"
    request.decided_at = timezone.now()
    request.decision_comment = comment or ""
    _touch(request)
    request.assignees.all().delete()
    _log(request, "APPROVE", actor, from_status, comment or "", step=decided_step)
    _audit(
        audit_events.APPROVAL_DECISION,
        actor,
        request,
        from_status,
        {"decision": "APPROVED", "decided_step": decided_step},
    )
    _run_executor(request, actor)
    notify(
        [request.requester],
        f"{request.request_number} was approved",
        request.title,
        request,
    )
    return request


@_refusable
@transaction.atomic
def reject(actor, request_id, comment="", password=None) -> ApprovalRequest:
    comment = (comment or "").strip()
    request = _locked(request_id)
    _check_may_decide(actor, request, "REJECT")
    if not comment:
        _invalid("comment", "Say why you are rejecting this request.")
    _reauthenticate(actor, request, password)
    from_status = request.status
    request.status = "REJECTED"
    request.decided_at = timezone.now()
    request.decision_comment = comment
    _touch(request)
    request.assignees.all().delete()
    _log(request, "REJECT", actor, from_status, comment)
    _audit(
        audit_events.APPROVAL_DECISION,
        actor,
        request,
        from_status,
        {"decision": "REJECTED"},
    )
    _run_closed(request, actor)
    notify(
        [request.requester],
        f"{request.request_number} was rejected",
        comment[:300],
        request,
    )
    return request


@_refusable
@transaction.atomic
def cancel(actor, request_id, comment="") -> ApprovalRequest:
    request = _locked(request_id)
    if request.requester_id != actor.pk:
        _forbid("Only the person who raised a request can cancel it.", "not_requester")
    if request.status not in ("DRAFT", *OPEN_STATUSES):
        raise StateConflict("This request can no longer be cancelled.")
    from_status = request.status
    waiting = [a.user for a in request.assignees.select_related("user")]
    request.status = "CANCELLED"
    request.decided_at = timezone.now()
    _touch(request)
    request.assignees.all().delete()
    _log(request, "CANCEL", actor, from_status, comment or "")
    _audit(audit_events.APPROVAL_CANCELLED, actor, request, from_status)
    _run_closed(request, actor)
    if request.request_number:
        notify(waiting, f"{request.request_number} was cancelled", request.title, request)
    return request


@transaction.atomic
def add_comment(actor, request_id, comment) -> ApprovalRequest:
    comment = (comment or "").strip()
    request = _locked(request_id)
    is_assignee = request.assignees.filter(user=actor).exists()
    if request.requester_id != actor.pk and not is_assignee:
        _forbid("Only the requester and the approvers can comment.", "not_participant")
    if request.status == "DRAFT":
        raise StateConflict("Submit the request before commenting.")
    if not comment:
        _invalid("comment", "Write a comment.")
    _log(request, "COMMENT", actor, request.status, comment)
    _audit(audit_events.APPROVAL_COMMENTED, actor, request, request.status)
    if request.requester_id == actor.pk:
        recipients = [a.user for a in request.assignees.select_related("user")]
    else:
        recipients = [request.requester]
    notify(recipients, f"New comment on {request.request_number}", comment[:300], request)
    return request


# --- What an approved (or closed) request does ----------------------------------------


def _run_executor(request, approver):
    if request.request_type == ROLE_GRANT:
        _execute_role_grant(request, approver)
    elif request.request_type == TZS_LIMITS_CHANGE:
        _execute_tzs_change(request, approver)


def _run_closed(request, actor):
    if request.request_type == TZS_LIMITS_CHANGE:
        TzsLimitPolicy.objects.filter(pk=request.payload.get("policy_id"), state="PROPOSED").update(
            state="REJECTED"
        )


def _execute_role_grant(request, approver):
    payload = request.payload
    user = User.objects.get(pk=payload["user_id"])
    role = Role.objects.get(pk=payload["role_id"])
    department = (
        Department.objects.get(pk=payload["department_id"])
        if payload.get("department_id")
        else None
    )
    rbac_services.assign_role_approved(
        request.requester,
        approver,
        user,
        role,
        request_number=request.request_number,
        department=department,
        valid_from=date.fromisoformat(payload["valid_from"]) if payload.get("valid_from") else None,
        valid_to=date.fromisoformat(payload["valid_to"]) if payload.get("valid_to") else None,
    )
    notify([user], f"You have been given the role {role.name}", request.request_number, request)


def _execute_tzs_change(request, approver):
    policy = TzsLimitPolicy.objects.select_for_update().get(pk=request.payload["policy_id"])
    old = TzsLimitPolicy.objects.filter(state="ACTIVE").first()
    if old is not None:
        old.state = "SUPERSEDED"
        old.save(update_fields=["state"])
    policy.state = "ACTIVE"
    policy.is_ratified = True
    policy.ratified_by = approver
    policy.ratified_at = timezone.now()
    policy.save()
    audit(
        audit_events.TZS_POLICY_ACTIVATED,
        actor=approver,
        object_type="approvals.TzsLimitPolicy",
        object_id=policy.pk,
        changes={
            "low_max": {"from": old.low_max if old else None, "to": policy.low_max},
            "medium_max": {"from": old.medium_max if old else None, "to": policy.medium_max},
            "always_high": {"from": old.always_high if old else None, "to": policy.always_high},
        },
        metadata={
            "version": policy.version_number,
            "request_number": request.request_number,
            "proposed_by": request.requester.username,
        },
    )


# --- Sensitive role grants (D-044) -----------------------------------------------------


@transaction.atomic
def request_role_grant(
    actor, *, user, role, reason, department=None, valid_from=None, valid_to=None
) -> ApprovalRequest:
    reason = (reason or "").strip()
    if not reason:
        _invalid("reason", "Say why this person needs this role.")
    if user.pk == actor.pk:
        _forbid("You cannot ask for a role for yourself.", "self_escalation")
    if not user.is_active:
        _invalid("user", "This person's account is not active.")
    if not role.is_active:
        _invalid("role", "This role is not active.")
    if not rbac_services.is_sensitive_role(role):
        _invalid("role", "This role is not sensitive; assign it directly from the user's page.")
    if valid_from and valid_to and valid_to < valid_from:
        _invalid("valid_to", "The end date cannot be before the start date.")
    if UserRole.objects.filter(
        user=user, role=role, department=department, revoked_at__isnull=True
    ).exists():
        _invalid("role", "This person already holds this role there.")
    duplicate = ApprovalRequest.objects.filter(
        request_type=ROLE_GRANT,
        status__in=OPEN_STATUSES,
        payload__user_id=str(user.pk),
        payload__role_id=str(role.pk),
    )
    if duplicate.exists():
        _invalid("role", "There is already an open request for this person and role.")
    request = ApprovalRequest(
        request_type=ROLE_GRANT,
        title=f"Grant {role.name} to {user.full_name}",
        description=reason,
        requester=actor,
        department_id=user.department_id,
        payload={
            "user_id": str(user.pk),
            "role_id": str(role.pk),
            "role_name": role.name,
            "user_name": user.full_name,
            "department_id": str(department.pk) if department else None,
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_to": valid_to.isoformat() if valid_to else None,
            "reasons": rbac_services.role_sensitivity(role),
        },
    )
    request.save()
    _log(request, "CREATE", actor, "", step=0)
    _audit(audit_events.APPROVAL_CREATED, actor, request, "")
    _submit_locked(actor, request)
    return request


# --- TZS limits (D-020, D-066) ---------------------------------------------------------


@transaction.atomic
def propose_tzs_limits(actor, *, low_max, medium_max, always_high, reason) -> ApprovalRequest:
    reason = (reason or "").strip()
    if not reason:
        _invalid("reason", "Say why the limits should change.")
    try:
        low, medium = int(low_max), int(medium_max)
    except (TypeError, ValueError):
        _invalid("low_max", "Enter whole numbers of shillings.")
    if low < 0 or medium <= low or medium > MAX_AMOUNT:
        _invalid("medium_max", "The second limit must be higher than the first.")
    unknown = [k for k in always_high or [] if k not in limits.ALWAYS_HIGH_KINDS]
    if unknown:
        _invalid("always_high", "Unknown kind of request.")
    kinds = sorted(set(always_high or []))
    if TzsLimitPolicy.objects.filter(state="PROPOSED").exists():
        raise StateConflict("A change to the limits is already waiting for approval.")
    active = limits.active_policy()
    if (
        active
        and active.is_ratified
        and (active.low_max, active.medium_max, sorted(active.always_high)) == (low, medium, kinds)
    ):
        _invalid("low_max", "These are already the limits in force.")
    last = TzsLimitPolicy.objects.order_by("-version_number").first()
    policy = TzsLimitPolicy.objects.create(
        version_number=(last.version_number + 1) if last else 1,
        state="PROPOSED",
        low_max=low,
        medium_max=medium,
        always_high=kinds,
        reason=reason[:500],
        created_by=actor,
    )
    request = ApprovalRequest(
        request_type=TZS_LIMITS_CHANGE,
        title=f"TZS limits, version {policy.version_number}",
        description=reason,
        requester=actor,
        department_id=actor.department_id,
        payload={
            "policy_id": str(policy.pk),
            "low_max": low,
            "medium_max": medium,
            "always_high": kinds,
        },
    )
    request.save()
    policy.request = request
    policy.save(update_fields=["request"])
    _log(request, "CREATE", actor, "", step=0)
    _audit(audit_events.APPROVAL_CREATED, actor, request, "")
    _submit_locked(actor, request)
    return request


# --- Reading -----------------------------------------------------------------------------


def visible_requests(user):
    """Requests this person may see: their own, those in their scope, and those they decide."""
    scoped = filter_queryset(user, "approvals", "VIEW", ApprovalRequest.objects.all())
    mine = ApprovalRequest.objects.filter(
        Q(assignees__user=user) | Q(actions__actor=user) | Q(requester=user)
    )
    return ApprovalRequest.objects.filter(
        Q(pk__in=scoped.values("pk")) | Q(pk__in=mine.values("pk"))
    )


def pending_for(user):
    return ApprovalRequest.objects.filter(
        status__in=OPEN_STATUSES, assignees__user=user, assignees__step=F_step()
    ).distinct()


def F_step():  # noqa: N802
    from django.db.models import F

    return F("current_step")


def open_requests_blocker(department):
    count = ApprovalRequest.objects.filter(department=department, status__in=OPEN_STATUSES).count()
    if count:
        return f"{count} approval request(s) from this department are still open."
    return None

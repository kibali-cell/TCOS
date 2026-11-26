"""Shapes sent to the client. Input serializers carry content only; never authority."""

from rest_framework import serializers

from . import limits
from .models import OPEN_STATUSES, ROLE_GRANT, TZS_LIMITS_CHANGE

TYPE_LABELS = {
    "GENERAL": "General request",
    ROLE_GRANT: "Sensitive role grant",
    TZS_LIMITS_CHANGE: "TZS limits change",
}


class DraftSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)  # idempotency key from a device
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    amount_tzs = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    kind = serializers.CharField(required=False, allow_blank=True, max_length=40)
    local_reference = serializers.CharField(required=False, allow_blank=True, max_length=60)
    created_offline = serializers.BooleanField(required=False)
    origin_device_id = serializers.UUIDField(required=False, allow_null=True)
    client_created_at = serializers.DateTimeField(required=False, allow_null=True)


class CommentSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, max_length=3000)


class DecisionSerializer(CommentSerializer):
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)


class RoleGrantSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role = serializers.UUIDField()
    department = serializers.UUIDField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=1000)


class TzsProposalSerializer(serializers.Serializer):
    low_max = serializers.IntegerField(min_value=0)
    medium_max = serializers.IntegerField(min_value=1)
    always_high = serializers.ListField(child=serializers.CharField(), required=False)
    reason = serializers.CharField(max_length=500)


def _person(user):
    return {"id": str(user.pk), "name": user.full_name or user.username} if user else None


def _route_state(request, entry):
    order = entry["order"]
    if request.status == "APPROVED":
        return "done"
    if request.status in OPEN_STATUSES:
        if order < request.current_step:
            return "done"
        return "current" if order == request.current_step else "waiting"
    return "stopped" if order >= max(request.current_step, 1) else "done"


def _payload(request):
    data = request.payload or {}
    if request.request_type == ROLE_GRANT:
        return {
            "person": data.get("user_name"),
            "role": data.get("role_name"),
            "valid_from": data.get("valid_from"),
            "valid_to": data.get("valid_to"),
            "why_sensitive": data.get("reasons", []),
        }
    if request.request_type == TZS_LIMITS_CHANGE:
        return {
            "low_max": data.get("low_max"),
            "medium_max": data.get("medium_max"),
            "always_high": data.get("always_high", []),
        }
    kind = data.get("kind", "")
    return {"kind": kind, "kind_label": limits.ALWAYS_HIGH_KINDS.get(kind, "")}


def _abilities(request, viewer, assignee_ids):
    from apps.rbac.permissions import can

    mine = request.requester_id == viewer.pk
    open_ = request.status in OPEN_STATUSES
    decides = (
        open_ and not mine and viewer.pk in assignee_ids and can(viewer, "approvals", "APPROVE")
    )
    return {
        "edit": mine and request.status == "DRAFT" and request.request_type == "GENERAL",
        "submit": mine and request.status == "DRAFT" and request.request_type == "GENERAL",
        "cancel": mine and (request.status == "DRAFT" or open_),
        "review": decides and request.status == "SUBMITTED",
        "approve": decides,
        "reject": decides and can(viewer, "approvals", "REJECT"),
        "comment": (mine or viewer.pk in assignee_ids) and request.status != "DRAFT",
    }


def request_summary(request, viewer) -> dict:
    assignees = [a for a in request.assignees.all() if a.step == request.current_step]
    ids = {a.user_id for a in assignees}
    return {
        "id": str(request.pk),
        "request_number": request.request_number,
        "request_type": request.request_type,
        "type_label": TYPE_LABELS.get(request.request_type, request.request_type),
        "title": request.title,
        "status": request.status,
        "risk_level": request.risk_level,
        "amount_tzs": request.amount_tzs,
        "requester": _person(request.requester),
        "department": (
            {"id": str(request.department_id), "name": request.department.name}
            if request.department_id
            else None
        ),
        "current_step": request.current_step,
        "waiting_for": [_person(a.user) for a in assignees],
        "submitted_at": request.submitted_at,
        "decided_at": request.decided_at,
        "created_at": request.created_at,
        "can": _abilities(request, viewer, ids),
    }


def request_detail(request, viewer) -> dict:
    from apps.core import documents

    data = request_summary(request, viewer)
    data.update(
        can_attach_files=documents.PARENTS["approvals.ApprovalRequest"].can_attach(
            viewer, request.pk
        ),
        attachments=[
            documents.payload(d, viewer)
            for d in documents.list_for(viewer, "approvals.ApprovalRequest", request.pk)
        ],
        description=request.description,
        decision_comment=request.decision_comment,
        payload=_payload(request),
        version=request.version,
        local_reference=request.local_reference,
        created_offline=request.created_offline,
        needs_password=request.risk_level == "HIGH",
        route=[
            {
                "order": entry["order"],
                "label": entry["label"],
                "source": entry.get("source", ""),
                "escalated_to": entry.get("escalated_to"),
                "state": _route_state(request, entry),
            }
            for entry in request.route
        ],
        history=[
            {
                "id": action.pk,
                "action": action.action,
                "actor": _person(action.actor),
                "from_status": action.from_status,
                "to_status": action.to_status,
                "step": action.step,
                "comment": action.comment,
                "at": action.created_at,
            }
            for action in request.actions.select_related("actor")
        ],
    )
    return data


def policy_payload(policy) -> dict:
    return {
        "id": str(policy.pk),
        "version_number": policy.version_number,
        "state": policy.state,
        "state_label": policy.get_state_display(),
        "low_max": policy.low_max,
        "medium_max": policy.medium_max,
        "always_high": policy.always_high,
        "reason": policy.reason,
        "is_ratified": policy.is_ratified,
        "ratified_by": _person(policy.ratified_by),
        "ratified_at": policy.ratified_at,
        "request_id": str(policy.request_id) if policy.request_id else None,
        "created_at": policy.created_at,
    }

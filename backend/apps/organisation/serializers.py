"""Input validation and output shapes for the organisation API."""

from rest_framework import serializers

from apps.accounts.models import User
from apps.rbac.models import Role

from .models import ApprovalHierarchy, Department, Position, StaffAssignment
from .services import _describe_step


def _person(user):
    return {"id": str(user.pk), "full_name": user.full_name, "username": user.username}


# --- Output ----------------------------------------------------------------------------


def department_payload(department: Department, *, blockers=None) -> dict:
    data = {
        "id": str(department.id),
        "code": department.code,
        "name": department.name,
        "description": department.description,
        "parent": (
            {"id": str(department.parent_id), "name": department.parent.name}
            if department.parent_id
            else None
        ),
        "head": (
            {"id": str(department.head_id), "full_name": department.head.full_name}
            if department.head_id
            else None
        ),
        "is_active": department.is_active,
        "is_archived": department.is_archived,
        "archived_at": department.archived_at,
        "version": department.version,
        "staff_count": getattr(department, "staff_count", None),
        "position_count": getattr(department, "position_count", None),
        "updated_at": department.updated_at,
    }
    if blockers is not None:
        data["archive_blockers"] = blockers
    return data


def position_payload(position: Position, *, blockers=None) -> dict:
    data = {
        "id": str(position.id),
        "title": position.title,
        "department": {"id": str(position.department_id), "name": position.department.name},
        "reports_to": (
            {
                "id": str(position.reports_to_id),
                "title": position.reports_to.title,
                "department": position.reports_to.department.name,
            }
            if position.reports_to_id
            else None
        ),
        "is_department_head_position": position.is_department_head_position,
        "is_active": position.is_active,
        "is_archived": position.is_archived,
        "version": position.version,
        "holder_count": getattr(position, "holder_count", None),
    }
    if blockers is not None:
        data["archive_blockers"] = blockers
    return data


def assignment_payload(assignment: StaffAssignment) -> dict:
    return {
        "id": str(assignment.id),
        "user": _person(assignment.user),
        "position": {"id": str(assignment.position_id), "title": assignment.position.title},
        "department": {
            "id": str(assignment.department_id),
            "name": assignment.department.name,
        },
        "is_primary": assignment.is_primary,
        "reports_to_user": (
            _person(assignment.reports_to_user) if assignment.reports_to_user_id else None
        ),
        "start_date": assignment.start_date,
        "end_date": assignment.end_date,
        "is_current": assignment.end_date is None,
        "version": assignment.version,
    }


def step_payload(step: ApprovalHierarchy) -> dict:
    return {
        "step_order": step.step_order,
        "approver_type": step.approver_type,
        "label": _describe_step(step),
        "position": str(step.approver_position_id) if step.approver_position_id else None,
        "role": str(step.approver_role_id) if step.approver_role_id else None,
        "user": str(step.approver_user_id) if step.approver_user_id else None,
        "is_active": step.is_active,
    }


# --- Input -----------------------------------------------------------------------------


class DepartmentCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )


class DepartmentUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )


class HeadSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class PositionCreateSerializer(serializers.Serializer):
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    title = serializers.CharField(max_length=150)
    reports_to = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(), required=False, allow_null=True
    )
    is_department_head_position = serializers.BooleanField(required=False)


class PositionUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150, required=False)
    reports_to = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(), required=False, allow_null=True
    )
    is_department_head_position = serializers.BooleanField(required=False)


class AssignmentCreateSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    position = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all())
    is_primary = serializers.BooleanField(required=False, allow_null=True)
    reports_to_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    start_date = serializers.DateField(required=False)


class AssignmentUpdateSerializer(serializers.Serializer):
    reports_to_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), allow_null=True
    )


class EndAssignmentSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False)


class TransferSerializer(serializers.Serializer):
    position = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all())


class StepSerializer(serializers.Serializer):
    approver_type = serializers.ChoiceField(choices=ApprovalHierarchy.ApproverType.values)
    position = serializers.UUIDField(required=False, allow_null=True)
    role = serializers.UUIDField(required=False, allow_null=True)
    user = serializers.UUIDField(required=False, allow_null=True)


class ChainSerializer(serializers.Serializer):
    steps = StepSerializer(many=True)


def role_option(role: Role) -> dict:
    return {"id": str(role.pk), "name": role.name}

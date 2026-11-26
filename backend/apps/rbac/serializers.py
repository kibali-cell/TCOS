from rest_framework import serializers

from apps.organisation.models import Department

from .models import Role, UserRole
from .services import role_sensitivity


class GrantSerializer(serializers.Serializer):
    module = serializers.CharField(max_length=60)
    action = serializers.CharField(max_length=20)
    scope = serializers.CharField(max_length=12)


class RoleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    requires_two_factor = serializers.BooleanField(required=False)


class RoleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    grants = GrantSerializer(many=True, required=False)


class RoleGrantsSerializer(serializers.Serializer):
    grants = GrantSerializer(many=True)


def role_summary(role: Role, *, holders: int | None = None) -> dict:
    data = {
        "id": str(role.id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "requires_two_factor": role.requires_two_factor,
        # Needs a second person's approval to grant (D-044, D-065).
        "sensitive_reasons": role_sensitivity(role),
    }
    data["is_sensitive"] = bool(data["sensitive_reasons"])
    if holders is not None:
        data["holders"] = holders
    return data


def role_detail(role: Role) -> dict:
    data = role_summary(role)
    data["grants"] = [
        {"module": g.permission.module, "action": g.permission.action, "scope": g.scope}
        for g in role.grants.select_related("permission").order_by(
            "permission__module", "permission__action"
        )
    ]
    return data


class AssignRoleSerializer(serializers.Serializer):
    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all())
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)


def assignment_payload(assignment: UserRole) -> dict:
    return {
        "id": str(assignment.id),
        "role": {
            "id": str(assignment.role_id),
            "code": assignment.role.code,
            "name": assignment.role.name,
        },
        "department": (
            {"id": str(assignment.department_id), "name": assignment.department.name}
            if assignment.department_id
            else None
        ),
        "valid_from": assignment.valid_from,
        "valid_to": assignment.valid_to,
        "granted_at": assignment.granted_at,
        "revoked_at": assignment.revoked_at,
    }

"""Role and role-assignment management.

All writes go through here so the protections cannot be bypassed by a view:

* **No self-escalation.** Nobody may assign a role to themselves, change their own
  assignments, or change the permissions of a role they currently hold.
* **Lock-out guards.** The Administrator role must keep `users.MANAGE_USERS` on everything,
  cannot be deactivated or deleted, and its last working holder cannot be removed.
* Seeded roles cannot be deleted; roles with any assignment history cannot be deleted
  (deactivate them instead).

Audit events for every change are written from Slice 3.
"""

from __future__ import annotations

import re
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .constants import ACTIONS, ADMINISTRATOR_ROLE, ALL, SCOPES
from .models import Permission, Role, RolePermission, UserRole

REQUIRED_ADMIN_GRANT = ("users", "MANAGE_USERS", ALL)


def _forbid(message: str, code: str):
    raise PermissionDenied(message, code)


def holds_role(user, role: Role) -> bool:
    """True if the user has a live (not revoked) assignment of the role."""
    return UserRole.objects.filter(user=user, role=role, revoked_at__isnull=True).exists()


# --- Roles ---------------------------------------------------------------------------


def _code_from_name(name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:50] or "ROLE"
    code, n = base, 2
    while Role.objects.filter(code=code).exists():
        code = f"{base}_{n}"
        n += 1
    return code


def _clean_grants(grants) -> dict[tuple[str, str], str]:
    """Validate a list of {module, action, scope} and return {(module, action): scope}."""
    cleaned: dict[tuple[str, str], str] = {}
    errors = []
    valid = set(Permission.objects.values_list("module", "action"))
    for index, item in enumerate(grants):
        key = (item.get("module"), item.get("action"))
        scope = item.get("scope")
        if key not in valid or key[1] not in ACTIONS:
            errors.append(f"Row {index + 1}: unknown permission {key[0]}.{key[1]}.")
        elif scope not in SCOPES:
            errors.append(f"Row {index + 1}: scope must be one of {', '.join(SCOPES)}.")
        elif key in cleaned:
            errors.append(f"Row {index + 1}: {key[0]}.{key[1]} is listed twice.")
        else:
            cleaned[key] = scope
    if errors:
        raise ValidationError({"grants": errors})
    return cleaned


def _protect_administrator_grants(role: Role, cleaned) -> None:
    if role.code == ADMINISTRATOR_ROLE:
        module, action, scope = REQUIRED_ADMIN_GRANT
        if cleaned.get((module, action)) != scope:
            raise ValidationError(
                {"grants": ["The Administrator role must keep Manage Users on Users (All)."]}
            )


@transaction.atomic
def create_role(actor, *, name: str, description: str = "", grants=()) -> Role:
    name = (name or "").strip()
    if not name:
        raise ValidationError({"name": ["A name is required."]})
    if Role.objects.filter(name__iexact=name).exists():
        raise ValidationError({"name": ["A role with this name already exists."]})
    cleaned = _clean_grants(grants)
    role = Role.objects.create(
        code=_code_from_name(name),
        name=name,
        description=(description or "").strip(),
        created_by=actor,
    )
    _write_grants(role, cleaned, actor)
    return role


@transaction.atomic
def update_role(actor, role: Role, *, name=None, description=None, is_active=None) -> Role:
    if holds_role(actor, role):
        _forbid("You cannot change a role that you hold yourself.", "self_escalation")
    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError({"name": ["A name is required."]})
        if Role.objects.filter(name__iexact=name).exclude(pk=role.pk).exists():
            raise ValidationError({"name": ["A role with this name already exists."]})
        role.name = name
    if description is not None:
        role.description = description.strip()
    if is_active is not None:
        if role.code == ADMINISTRATOR_ROLE and not is_active:
            raise ValidationError({"is_active": ["The Administrator role cannot be deactivated."]})
        role.is_active = is_active
    role.save()
    return role


@transaction.atomic
def delete_role(actor, role: Role) -> None:
    if role.is_system:
        raise ValidationError({"detail": ["Built-in roles cannot be deleted."]})
    if holds_role(actor, role):
        _forbid("You cannot change a role that you hold yourself.", "self_escalation")
    if UserRole.objects.filter(role=role).exists():
        raise ValidationError(
            {"detail": ["This role has been assigned to people. Deactivate it instead."]}
        )
    role.delete()


def _write_grants(role: Role, cleaned, actor) -> None:
    permissions = {(p.module, p.action): p for p in Permission.objects.all()}
    existing = {
        (g.permission.module, g.permission.action): g
        for g in role.grants.select_related("permission")
    }
    for key, grant in existing.items():
        if key not in cleaned:
            grant.delete()
    for key, scope in cleaned.items():
        grant = existing.get(key)
        if grant is None:
            RolePermission.objects.create(
                role=role, permission=permissions[key], scope=scope, granted_by=actor
            )
        elif grant.scope != scope:
            grant.scope = scope
            grant.granted_by = actor
            grant.save(update_fields=["scope", "granted_by"])


@transaction.atomic
def set_role_grants(actor, role: Role, grants) -> Role:
    """Replace the role's whole permission matrix. Each cell is its own row."""
    if holds_role(actor, role):
        _forbid("You cannot change the permissions of a role you hold yourself.", "self_escalation")
    cleaned = _clean_grants(grants)
    _protect_administrator_grants(role, cleaned)
    _write_grants(role, cleaned, actor)
    role.save()  # bumps updated_at
    return role


# --- Assignments ---------------------------------------------------------------------


def _working_administrators(exclude_assignment=None):
    """User ids that can currently administer: active account, live unrestricted assignment."""
    today = timezone.localdate()
    queryset = (
        UserRole.objects.filter(
            role__code=ADMINISTRATOR_ROLE,
            role__is_active=True,
            revoked_at__isnull=True,
            department__isnull=True,
            user__status="ACTIVE",
        )
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    )
    if exclude_assignment is not None:
        queryset = queryset.exclude(pk=exclude_assignment.pk)
    return set(queryset.values_list("user_id", flat=True))


@transaction.atomic
def assign_role(
    actor,
    user,
    role: Role,
    *,
    department=None,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> UserRole:
    if user.pk == actor.pk:
        _forbid("You cannot change your own roles.", "self_escalation")
    if not role.is_active:
        raise ValidationError({"role": ["This role is not active."]})
    if valid_from and valid_to and valid_to < valid_from:
        raise ValidationError({"valid_to": ["The end date cannot be before the start date."]})
    if department is not None and not department.is_active:
        raise ValidationError({"department": ["This department is not active."]})
    duplicate = UserRole.objects.filter(
        user=user, role=role, department=department, revoked_at__isnull=True
    )
    if duplicate.exists():
        raise ValidationError({"role": ["This person already holds this role there."]})
    return UserRole.objects.create(
        user=user,
        role=role,
        department=department,
        valid_from=valid_from,
        valid_to=valid_to,
        granted_by=actor,
    )


@transaction.atomic
def revoke_user_role(actor, assignment: UserRole) -> UserRole:
    if assignment.user_id == actor.pk:
        _forbid("You cannot change your own roles.", "self_escalation")
    if assignment.revoked_at is not None:
        raise ValidationError({"detail": ["This assignment has already been removed."]})
    if assignment.role.code == ADMINISTRATOR_ROLE:
        if not _working_administrators(exclude_assignment=assignment):
            raise ValidationError(
                {"detail": ["This is the last working Administrator and cannot be removed."]}
            )
    assignment.revoked_at = timezone.now()
    assignment.revoked_by = actor
    assignment.save(update_fields=["revoked_at", "revoked_by"])
    return assignment

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

from apps.audit import events as audit_events
from apps.audit.service import record as audit

from .constants import (
    ACTIONS,
    ADMINISTRATOR_ROLE,
    ALL,
    DECISION_ACTIONS,
    SCOPES,
    SENSITIVE_ACTIONS,
    SENSITIVE_MODULES,
)
from .models import Permission, Role, RolePermission, UserRole

REQUIRED_ADMIN_GRANT = ("users", "MANAGE_USERS", ALL)


def sensitivity_of(grants) -> list[str]:
    """Why a set of (module, action, scope) grants is sensitive. Empty means not sensitive.

    The rule is in ``constants.py`` (D-065). Reasons are plain sentences for the screen.
    """
    reasons = set()
    for module, action, scope in grants:
        if module in SENSITIVE_MODULES:
            reasons.add(f"Can {SENSITIVE_MODULES[module]} ({module})")
        if action in SENSITIVE_ACTIONS:
            reasons.add(f"Can {SENSITIVE_ACTIONS[action]} ({module})")
        if action in DECISION_ACTIONS and scope != "ASSIGNED" and scope != "OWN":
            reasons.add(f"Can decide requests beyond those assigned to them ({module})")
    return sorted(reasons)


def role_sensitivity(role: Role) -> list[str]:
    return sensitivity_of(
        (g.permission.module, g.permission.action, g.scope)
        for g in role.grants.select_related("permission")
    )


def is_sensitive_role(role: Role) -> bool:
    return bool(role_sensitivity(role))


def _forbid(message: str, code: str):
    raise PermissionDenied(message, code)


def holds_role(user, role: Role) -> bool:
    """True if the user has a live (not revoked) assignment of the role."""
    return UserRole.objects.filter(user=user, role=role, revoked_at__isnull=True).exists()


def _cell(module: str, action: str, scope: str) -> str:
    return f"{module}.{action}={scope}"


def _role_fields(role: Role) -> dict:
    return {"name": role.name, "description": role.description, "is_active": role.is_active}


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
    audit(
        audit_events.ROLE_CREATED,
        actor=actor,
        object_type="rbac.Role",
        object_id=role.pk,
        changes={
            **{k: {"from": None, "to": v} for k, v in _role_fields(role).items()},
            "grants": {"from": [], "to": sorted(_cell(m, a, sc) for (m, a), sc in cleaned.items())},
        },
        metadata={"code": role.code},
    )
    return role


@transaction.atomic
def update_role(actor, role: Role, *, name=None, description=None, is_active=None) -> Role:
    if holds_role(actor, role):
        _forbid("You cannot change a role that you hold yourself.", "self_escalation")
    before = _role_fields(role)
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
    after = _role_fields(role)
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if changes:
        audit(
            audit_events.ROLE_UPDATED,
            actor=actor,
            object_type="rbac.Role",
            object_id=role.pk,
            changes=changes,
            metadata={"code": role.code},
        )
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
    audit(
        audit_events.ROLE_DELETED,
        actor=actor,
        object_type="rbac.Role",
        object_id=role.pk,
        changes={k: {"from": v, "to": None} for k, v in _role_fields(role).items()},
        metadata={"code": role.code},
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
    old = {
        (g.permission.module, g.permission.action): g.scope
        for g in role.grants.select_related("permission")
    }
    new_reasons = set(sensitivity_of((m, a, sc) for (m, a), sc in cleaned.items()))
    old_reasons = set(sensitivity_of((m, a, sc) for (m, a), sc in old.items()))
    if new_reasons - old_reasons and role.user_roles.filter(revoked_at__isnull=True).exists():
        # Otherwise an administrator could widen a role its holders already have and so
        # hand them sensitive access without the second person's approval (D-067).
        _forbid(
            "This role has people in it, so it cannot gain sensitive access here. Create a "
            "new role with that access; people can then be given it through an approval.",
            "approval_required",
        )
    _write_grants(role, cleaned, actor)
    role.save()  # bumps updated_at
    added = sorted(_cell(m, a, sc) for (m, a), sc in cleaned.items() if (m, a) not in old)
    removed = sorted(_cell(m, a, sc) for (m, a), sc in old.items() if (m, a) not in cleaned)
    changed = sorted(
        f"{m}.{a}: {old[(m, a)]} -> {sc}"
        for (m, a), sc in cleaned.items()
        if old.get((m, a)) not in (None, sc)
    )
    if added or removed or changed:
        audit(
            audit_events.PERMISSION_CHANGED,
            actor=actor,
            object_type="rbac.Role",
            object_id=role.pk,
            changes={"added": added, "removed": removed, "scope_changed": changed},
            metadata={
                "code": role.code,
                "holders": role.user_roles.filter(revoked_at__isnull=True).count(),
            },
        )
    return role


# --- Assignments ---------------------------------------------------------------------


def working_administrators(exclude_assignment=None):
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
    if is_sensitive_role(role):
        _forbid(
            "This role gives sensitive access, so a second person must approve it. "
            "Raise a role-grant request in the Approval Centre instead.",
            "approval_required",
        )
    return _create_assignment(
        actor, user, role, department=department, valid_from=valid_from, valid_to=valid_to
    )


def _create_assignment(
    actor,
    user,
    role: Role,
    *,
    department=None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    extra_metadata=None,
) -> UserRole:
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
    assignment = UserRole.objects.create(
        user=user,
        role=role,
        department=department,
        valid_from=valid_from,
        valid_to=valid_to,
        granted_by=actor,
    )
    audit(
        audit_events.ROLE_ASSIGNED,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=department.pk if department else None,
        metadata={
            "role": role.code,
            "department": department.name if department else None,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "assignment_id": assignment.pk,
            **(extra_metadata or {}),
        },
    )
    return assignment


@transaction.atomic
def assign_role_approved(
    requester,
    approver,
    user,
    role: Role,
    *,
    request_number: str,
    department=None,
    valid_from=None,
    valid_to=None,
) -> UserRole:
    """Create the assignment an approved request asked for. Called only by the Approval Centre.

    Re-checks the rules at the moment of granting, because time has passed since the request.
    """
    if user.pk in (requester.pk, approver.pk):
        _forbid("Nobody can grant or approve a role for themselves.", "self_escalation")
    if approver.pk == requester.pk:
        _forbid("The person who asked cannot be the approver.", "self_decision")
    if not user.is_active:
        raise ValidationError({"detail": ["The person's account is no longer active."]})
    return _create_assignment(
        requester,
        user,
        role,
        department=department,
        valid_from=valid_from,
        valid_to=valid_to,
        extra_metadata={
            "approval_request": request_number,
            "approved_by": approver.username,
            "requested_by": requester.username,
        },
    )


@transaction.atomic
def revoke_user_role(actor, assignment: UserRole) -> UserRole:
    if assignment.user_id == actor.pk:
        _forbid("You cannot change your own roles.", "self_escalation")
    if assignment.revoked_at is not None:
        raise ValidationError({"detail": ["This assignment has already been removed."]})
    if assignment.role.code == ADMINISTRATOR_ROLE:
        if not working_administrators(exclude_assignment=assignment):
            raise ValidationError(
                {"detail": ["This is the last working Administrator and cannot be removed."]}
            )
    assignment.revoked_at = timezone.now()
    assignment.revoked_by = actor
    assignment.save(update_fields=["revoked_at", "revoked_by"])
    audit(
        audit_events.ROLE_REVOKED,
        actor=actor,
        object_type="accounts.User",
        object_id=assignment.user_id,
        department_id=assignment.department_id,
        metadata={"role": assignment.role.code, "assignment_id": assignment.pk},
    )
    return assignment

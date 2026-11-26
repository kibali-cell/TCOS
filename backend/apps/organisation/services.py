"""Organisation structure: every change goes through here, audited in the same transaction.

Rules enforced here (and, where the database can express them, by constraints too):

* **No cycles.** A department cannot sit under itself, a position cannot report to itself
  through any chain, and a person's reporting line (an override, or the position's line)
  cannot lead back to them.
* **Archive, never delete.** Archiving is blocked, with a plain-language reason, while
  people, sub-departments or reporting lines still depend on the record.
* **One main assignment.** A person has at most one current *main* (primary) assignment;
  their ``user.department`` follows it, which is what department-scoped access reads
  (see ``apps.rbac.permissions``). Ending or changing it changes what they can reach at
  once.
* **Assignments take effect immediately.** There are no future-dated moves; ``start_date``
  cannot be in the future.
* Structure changes are serialised with one advisory lock, so two simultaneous edits
  cannot together create a cycle.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit import events as audit_events
from apps.audit.changes import diff, record_created, record_updated, snapshot
from apps.audit.service import record as audit
from apps.rbac.models import Role

from .models import (
    DEFAULT_REQUEST_TYPE,
    ApprovalHierarchy,
    Department,
    Position,
    StaffAssignment,
)

STRUCTURE_LOCK_KEY = 7_340_181_222
MAX_CHAIN_STEPS = 6
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")
REQUEST_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")

# Later slices add checks here, e.g. Slice 5: "N requests are still open in this department".
# Each takes a Department and returns a sentence (the reason archiving is blocked) or None.
ARCHIVE_BLOCKERS: list[Callable[[Department], str | None]] = []


def _invalid(field: str, message: str):
    raise ValidationError({field: [message]})


def _lock_structure():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [STRUCTURE_LOCK_KEY])


def _touch(instance, actor, *, bump=True):
    if bump:
        instance.version += 1
    instance.updated_by = actor


def _clean_text(value, field, *, maximum, required=True):
    text = (value or "").strip()
    if required and not text:
        _invalid(field, "This field is required.")
    if len(text) > maximum:
        _invalid(field, f"Use at most {maximum} characters.")
    return text


def _fresh(model, instance):
    """Re-read a row the caller passed in, so decisions use what is stored now."""
    return None if instance is None else model.objects.get(pk=instance.pk)


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


# --- Departments ---------------------------------------------------------------------


def _would_loop(model, own_pk, new_parent_pk, link: str) -> bool:
    """Walk up the stored ``link`` chain from the new parent; True if it reaches ``own_pk``."""
    seen = set()
    node = new_parent_pk
    while node is not None and node not in seen:
        if node == own_pk:
            return True
        seen.add(node)
        node = model.objects.filter(pk=node).values_list(link, flat=True).first()
    return False


def _check_parent(department: Department | None, parent: Department | None):
    """Returns the parent as stored now (or None)."""
    parent = _fresh(Department, parent)
    if parent is None:
        return None
    if parent.is_archived:
        _invalid("parent", "This department is archived and cannot have sub-departments.")
    if department is not None and _would_loop(Department, department.pk, parent.pk, "parent_id"):
        _invalid(
            "parent", "A department cannot sit under itself or one of its own sub-departments."
        )
    return parent


def _check_names(department: Department | None, name: str, code: str | None = None):
    others = Department.objects.exclude(pk=department.pk) if department else Department.objects
    if others.filter(name__iexact=name).exists():
        _invalid("name", "Another department already has this name.")
    if code and others.filter(code=code).exists():
        _invalid("code", "Another department already has this code.")


@transaction.atomic
def create_department(
    actor, *, code, name, description="", parent: Department | None = None
) -> Department:
    _lock_structure()
    code = (code or "").strip().upper()
    if not CODE_PATTERN.match(code):
        _invalid(
            "code",
            "Use 2 to 40 capital letters, digits or underscores, starting with a letter.",
        )
    name = _clean_text(name, "name", maximum=150)
    description = _clean_text(description, "description", maximum=2000, required=False)
    _check_names(None, name, code)
    parent = _check_parent(None, parent)
    department = Department.objects.create(
        code=code,
        name=name,
        description=description,
        parent=parent,
        created_by=actor,
        updated_by=actor,
    )
    record_created(actor, department)
    return department


_UNSET = object()


@transaction.atomic
def update_department(
    actor, department: Department, *, name=_UNSET, description=_UNSET, parent=_UNSET
) -> Department:
    """Rename, describe or move a department. The code never changes."""
    _lock_structure()
    department = Department.objects.select_for_update().get(pk=department.pk)
    if department.is_archived:
        _invalid("detail", "This department is archived. Restore it before changing it.")
    before = snapshot(department)
    if name is not _UNSET:
        department.name = _clean_text(name, "name", maximum=150)
        _check_names(department, department.name)
    if description is not _UNSET:
        department.description = _clean_text(
            description, "description", maximum=2000, required=False
        )
    if parent is not _UNSET:
        department.parent = _check_parent(department, parent)
    if snapshot(department) == before:
        return department
    _touch(department, actor)
    department.save()
    record_updated(actor, department, before)
    return department


def _current_assignments(department: Department):
    return StaffAssignment.objects.filter(department=department, end_date__isnull=True)


@transaction.atomic
def set_department_head(actor, department: Department, user: User | None) -> Department:
    """Name the department head (or clear it). The head must work in the department."""
    _lock_structure()
    department = Department.objects.select_for_update().get(pk=department.pk)
    if department.is_archived:
        _invalid("detail", "This department is archived.")
    user = _fresh(User, user)
    if user is not None:
        if user.status != User.Status.ACTIVE:
            _invalid("head", "This person's account is not active.")
        if not _current_assignments(department).filter(user=user).exists():
            _invalid(
                "head",
                "A department head must hold a position in the department. "
                "Assign this person to a position there first.",
            )
    before = snapshot(department)
    department.head = user
    if snapshot(department) == before:
        return department
    _touch(department, actor)
    department.save()
    record_updated(actor, department, before)
    return department


def department_blockers(department: Department) -> list[str]:
    """Plain-language reasons the department cannot be archived yet. Empty means it can."""
    reasons = []
    children = Department.objects.filter(parent=department, is_archived=False).count()
    if children:
        reasons.append(
            f"it still has {_plural(children, 'active sub-department')} "
            "(move or archive them first)"
        )
    people = (
        User.objects.filter(
            Q(staff_assignments__department=department, staff_assignments__end_date__isnull=True)
            | Q(department=department, status=User.Status.ACTIVE)
        )
        .distinct()
        .count()
    )
    if people:
        reasons.append(
            f"{_plural(people, 'person', 'people')} still "
            f"{'works' if people == 1 else 'work'} in it (move them or end their assignments first)"
        )
    outside_reports = Position.objects.filter(
        reports_to__department=department, is_archived=False
    ).exclude(department=department)
    if outside_reports.exists():
        reasons.append(
            f"{_plural(outside_reports.count(), 'position')} in other departments report "
            "to its positions (change those reporting lines first)"
        )
    outside_steps = (
        ApprovalHierarchy.objects.filter(approver_position__department=department, is_active=True)
        .exclude(department=department)
        .count()
    )
    if outside_steps:
        reasons.append(
            f"{_plural(outside_steps, 'approval step')} in other departments name its "
            "positions (change those chains first)"
        )
    for check in ARCHIVE_BLOCKERS:
        reason = check(department)
        if reason:
            reasons.append(reason)
    return reasons


@transaction.atomic
def archive_department(actor, department: Department, *, reason: str = "") -> Department:
    """Archive a department and its positions. Blocked while anything depends on it."""
    _lock_structure()
    department = Department.objects.select_for_update().get(pk=department.pk)
    if department.is_archived:
        return department
    blockers = department_blockers(department)
    if blockers:
        _invalid(
            "detail",
            "This department cannot be archived yet: " + "; ".join(blockers) + ".",
        )
    before = snapshot(department)
    now = timezone.now()
    department.is_archived = True
    department.is_active = False
    department.archived_at = now
    department.archived_by = actor
    department.head = None
    _touch(department, actor)
    department.save()

    positions = list(Position.objects.filter(department=department, is_archived=False))
    for position in positions:
        position.is_archived = True
        position.is_active = False
        position.archived_at = now
        position.archived_by = actor
        _touch(position, actor)
        position.save()
    ApprovalHierarchy.objects.filter(department=department, is_active=True).update(is_active=False)

    audit(
        audit_events.RECORD_ARCHIVED,
        actor=actor,
        object_type=department._meta.label,
        object_id=department.pk,
        department_id=department.pk,
        changes=diff(before, snapshot(department)),
        metadata={
            "reason": (reason or "")[:300],
            "archived_positions": [position.title for position in positions],
        },
    )
    return department


@transaction.atomic
def restore_department(actor, department: Department) -> Department:
    """Bring an archived department back. Its positions and chains stay archived."""
    _lock_structure()
    department = Department.objects.select_for_update().get(pk=department.pk)
    if not department.is_archived:
        return department
    if department.parent_id and department.parent.is_archived:
        _invalid("detail", "Restore its parent department first.")
    before = snapshot(department)
    department.is_archived = False
    department.is_active = True
    department.archived_at = None
    department.archived_by = None
    _touch(department, actor)
    department.save()
    audit(
        audit_events.RECORD_UPDATED,
        actor=actor,
        object_type=department._meta.label,
        object_id=department.pk,
        department_id=department.pk,
        changes=diff(before, snapshot(department)),
        metadata={"action": "restored"},
    )
    return department


# --- Positions -----------------------------------------------------------------------


def _check_boss(position: Position | None, boss: Position | None):
    """Returns the boss position as stored now (or None)."""
    boss = _fresh(Position, boss)
    if boss is None:
        return None
    if boss.is_archived:
        _invalid("reports_to", "This position is archived.")
    if position is not None and _would_loop(Position, position.pk, boss.pk, "reports_to_id"):
        _invalid("reports_to", "A position cannot report to itself or to one that reports to it.")
    return boss


def _check_single_head(position: Position | None, department: Department, flag: bool):
    if not flag:
        return
    others = Position.objects.filter(
        department=department, is_department_head_position=True, is_archived=False
    )
    if position is not None:
        others = others.exclude(pk=position.pk)
    if others.exists():
        _invalid(
            "is_department_head_position",
            "This department already has a head position. Change that one first.",
        )


@transaction.atomic
def create_position(
    actor,
    *,
    department: Department,
    title,
    reports_to: Position | None = None,
    is_department_head_position: bool = False,
) -> Position:
    _lock_structure()
    department = _fresh(Department, department)
    if department.is_archived:
        _invalid("department", "This department is archived.")
    title = _clean_text(title, "title", maximum=150)
    if Position.objects.filter(department=department, title__iexact=title).exists():
        _invalid("title", "This department already has a position with this title.")
    reports_to = _check_boss(None, reports_to)
    _check_single_head(None, department, is_department_head_position)
    position = Position.objects.create(
        department=department,
        title=title,
        reports_to=reports_to,
        is_department_head_position=is_department_head_position,
        created_by=actor,
        updated_by=actor,
    )
    record_created(actor, position)
    return position


@transaction.atomic
def update_position(
    actor,
    position: Position,
    *,
    title=_UNSET,
    reports_to=_UNSET,
    is_department_head_position=_UNSET,
) -> Position:
    """Change a position's title, reporting line or head flag. Its department never changes."""
    _lock_structure()
    position = Position.objects.select_for_update().get(pk=position.pk)
    if position.is_archived:
        _invalid("detail", "This position is archived. Restore it before changing it.")
    before = snapshot(position)
    if title is not _UNSET:
        position.title = _clean_text(title, "title", maximum=150)
        clash = Position.objects.filter(
            department=position.department, title__iexact=position.title
        ).exclude(pk=position.pk)
        if clash.exists():
            _invalid("title", "This department already has a position with this title.")
    if reports_to is not _UNSET:
        position.reports_to = _check_boss(position, reports_to)
    if is_department_head_position is not _UNSET:
        _check_single_head(position, position.department, is_department_head_position)
        position.is_department_head_position = is_department_head_position
    if snapshot(position) == before:
        return position
    _touch(position, actor)
    position.save()
    if reports_to is not _UNSET:
        _assert_no_reporting_loop(
            User.objects.filter(
                staff_assignments__position=position, staff_assignments__end_date__isnull=True
            )
        )
    record_updated(actor, position, before)
    return position


def position_blockers(position: Position) -> list[str]:
    reasons = []
    holders = StaffAssignment.objects.filter(position=position, end_date__isnull=True).count()
    if holders:
        reasons.append(
            f"{_plural(holders, 'person', 'people')} currently "
            f"{'holds' if holders == 1 else 'hold'} it (end their assignments first)"
        )
    reports = Position.objects.filter(reports_to=position, is_archived=False).count()
    if reports:
        reasons.append(
            f"{_plural(reports, 'position')} report to it (change their reporting line first)"
        )
    steps = ApprovalHierarchy.objects.filter(approver_position=position, is_active=True).count()
    if steps:
        reasons.append(f"{_plural(steps, 'approval step')} name it (change those chains first)")
    return reasons


@transaction.atomic
def archive_position(actor, position: Position, *, reason: str = "") -> Position:
    _lock_structure()
    position = Position.objects.select_for_update().get(pk=position.pk)
    if position.is_archived:
        return position
    blockers = position_blockers(position)
    if blockers:
        _invalid("detail", "This position cannot be archived yet: " + "; ".join(blockers) + ".")
    before = snapshot(position)
    position.is_archived = True
    position.is_active = False
    position.archived_at = timezone.now()
    position.archived_by = actor
    _touch(position, actor)
    position.save()
    audit(
        audit_events.RECORD_ARCHIVED,
        actor=actor,
        object_type=position._meta.label,
        object_id=position.pk,
        department_id=position.department_id,
        changes=diff(before, snapshot(position)),
        metadata={"reason": (reason or "")[:300]},
    )
    return position


@transaction.atomic
def restore_position(actor, position: Position) -> Position:
    _lock_structure()
    position = Position.objects.select_for_update().get(pk=position.pk)
    if not position.is_archived:
        return position
    if position.department.is_archived:
        _invalid("detail", "Restore its department first.")
    if position.reports_to_id and position.reports_to.is_archived:
        _invalid("detail", "The position it reports to is archived. Restore that one first.")
    if position.is_department_head_position:
        _check_single_head(position, position.department, True)
    before = snapshot(position)
    position.is_archived = False
    position.is_active = True
    position.archived_at = None
    position.archived_by = None
    _touch(position, actor)
    position.save()
    audit(
        audit_events.RECORD_UPDATED,
        actor=actor,
        object_type=position._meta.label,
        object_id=position.pk,
        department_id=position.department_id,
        changes=diff(before, snapshot(position)),
        metadata={"action": "restored"},
    )
    return position


# --- Reporting lines between people ----------------------------------------------------


def _bosses_of(user_id) -> set:
    """Who a person reports to: a named override, else the holders of the position's boss."""
    bosses = set()
    for assignment in StaffAssignment.objects.filter(user_id=user_id, end_date__isnull=True):
        if assignment.reports_to_user_id:
            bosses.add(assignment.reports_to_user_id)
            continue
        boss_position = assignment.position.reports_to_id
        if boss_position:
            bosses.update(
                StaffAssignment.objects.filter(
                    position_id=boss_position, end_date__isnull=True
                ).values_list("user_id", flat=True)
            )
    bosses.discard(user_id)
    return bosses


def _leads_back(user_id) -> bool:
    """True if following reporting lines upwards from ``user_id`` returns to them."""
    seen: set = set()
    frontier = set(_bosses_of(user_id))
    while frontier:
        if user_id in frontier:
            return True
        seen |= frontier
        nxt: set = set()
        for person in frontier:
            nxt |= _bosses_of(person)
        frontier = nxt - seen
    return False


def _assert_no_reporting_loop(users):
    for user_id in list(users.values_list("pk", flat=True)):
        if _leads_back(user_id):
            _invalid(
                "detail",
                "That reporting line would make someone report, in the end, to themselves.",
            )


# --- Staff assignments -----------------------------------------------------------------


def _sync_primary_department(actor, user: User):
    """Keep ``user.department`` (read by department-scoped access) equal to the main assignment."""
    primary = (
        StaffAssignment.objects.filter(user=user, is_primary=True, end_date__isnull=True)
        .only("department_id")
        .first()
    )
    wanted = primary.department_id if primary else None
    if user.department_id == wanted:
        return
    old = user.department_id
    user.department_id = wanted
    user.save(update_fields=["department", "updated_at"])
    audit(
        audit_events.USER_UPDATED,
        actor=actor,
        object_type="accounts.User",
        object_id=user.pk,
        department_id=wanted,
        changes={"department_id": {"from": old, "to": wanted}},
        metadata={"source": "main staff assignment"},
    )


def _drop_head_if_gone(actor, user: User, department: Department):
    if department.head_id != user.pk:
        return
    if _current_assignments(department).filter(user=user).exists():
        return
    before = snapshot(department)
    department.head = None
    _touch(department, actor)
    department.save()
    record_updated(actor, department, before, metadata={"reason": "head left the department"})


@transaction.atomic
def assign_staff(
    actor,
    user: User,
    position: Position,
    *,
    is_primary: bool | None = None,
    reports_to_user: User | None = None,
    start_date=None,
) -> StaffAssignment:
    """Give a person a position. The first assignment becomes their main one."""
    _lock_structure()
    user = User.objects.select_for_update().get(pk=user.pk)
    position = Position.objects.select_related("department").get(pk=position.pk)
    if user.status != User.Status.ACTIVE:
        _invalid("user", "This person's account is not active.")
    if position.is_archived or position.department.is_archived:
        _invalid("position", "This position is archived.")
    today = timezone.localdate()
    start = start_date or today
    if start > today:
        _invalid("start_date", "An assignment cannot start in the future.")
    if StaffAssignment.objects.filter(user=user, position=position, end_date__isnull=True).exists():
        _invalid("position", "This person already holds this position.")
    has_primary = StaffAssignment.objects.filter(
        user=user, is_primary=True, end_date__isnull=True
    ).exists()
    if is_primary is None:
        is_primary = not has_primary
    if is_primary and has_primary:
        _invalid(
            "is_primary",
            "This person already has a main assignment. Use Transfer to move them, "
            "or add this one as an additional assignment.",
        )
    reports_to_user = _fresh(User, reports_to_user)
    if reports_to_user is not None and reports_to_user.pk == user.pk:
        _invalid("reports_to_user", "Nobody can report to themselves.")
    assignment = StaffAssignment.objects.create(
        user=user,
        position=position,
        department=position.department,
        is_primary=is_primary,
        reports_to_user=reports_to_user,
        start_date=start,
        created_by=actor,
        updated_by=actor,
    )
    _assert_no_reporting_loop(User.objects.filter(pk=user.pk))
    record_created(
        actor,
        assignment,
        metadata={"person": user.username, "position": position.title},
    )
    _sync_primary_department(actor, user)
    return assignment


@transaction.atomic
def end_assignment(actor, assignment: StaffAssignment, *, end_date=None) -> StaffAssignment:
    _lock_structure()
    assignment = StaffAssignment.objects.select_for_update().get(pk=assignment.pk)
    if assignment.end_date is not None:
        _invalid("detail", "This assignment has already ended.")
    today = timezone.localdate()
    end = end_date or today
    if end > today:
        _invalid("end_date", "An assignment cannot be ended in the future.")
    if end < assignment.start_date:
        _invalid("end_date", "The end date cannot be before the start date.")
    before = snapshot(assignment)
    assignment.end_date = end
    _touch(assignment, actor)
    assignment.save()
    record_updated(
        actor,
        assignment,
        before,
        metadata={"person": assignment.user.username, "action": "ended"},
    )
    _drop_head_if_gone(actor, assignment.user, assignment.department)
    _sync_primary_department(actor, assignment.user)
    return assignment


@transaction.atomic
def transfer_staff(actor, assignment: StaffAssignment, new_position: Position) -> StaffAssignment:
    """Move a person from one position to another in one step (history is kept)."""
    _lock_structure()
    assignment = StaffAssignment.objects.select_for_update().get(pk=assignment.pk)
    if assignment.end_date is not None:
        _invalid("detail", "This assignment has already ended.")
    if new_position.pk == assignment.position_id:
        _invalid("position", "They already hold this position.")
    was_primary = assignment.is_primary
    reports_to_user = assignment.reports_to_user
    user = assignment.user
    end_assignment(actor, assignment)
    return assign_staff(
        actor,
        user,
        new_position,
        is_primary=was_primary,
        reports_to_user=reports_to_user,
    )


@transaction.atomic
def make_primary(actor, assignment: StaffAssignment) -> StaffAssignment:
    """Make this the person's main assignment; their previous main one stays as additional."""
    _lock_structure()
    assignment = StaffAssignment.objects.select_for_update().get(pk=assignment.pk)
    if assignment.end_date is not None:
        _invalid("detail", "This assignment has ended.")
    if assignment.is_primary:
        return assignment
    for other in StaffAssignment.objects.select_for_update().filter(
        user=assignment.user, is_primary=True, end_date__isnull=True
    ):
        before = snapshot(other)
        other.is_primary = False
        _touch(other, actor)
        other.save()
        record_updated(actor, other, before, metadata={"action": "no longer main"})
    before = snapshot(assignment)
    assignment.is_primary = True
    _touch(assignment, actor)
    assignment.save()
    record_updated(actor, assignment, before, metadata={"action": "made main"})
    _sync_primary_department(actor, assignment.user)
    return assignment


@transaction.atomic
def set_reports_to_user(actor, assignment: StaffAssignment, boss: User | None) -> StaffAssignment:
    """Name who this person reports to, overriding the position's reporting line."""
    _lock_structure()
    assignment = StaffAssignment.objects.select_for_update().get(pk=assignment.pk)
    if assignment.end_date is not None:
        _invalid("detail", "This assignment has ended.")
    boss = _fresh(User, boss)
    if boss is not None:
        if boss.pk == assignment.user_id:
            _invalid("reports_to_user", "Nobody can report to themselves.")
        if boss.status != User.Status.ACTIVE:
            _invalid("reports_to_user", "This person's account is not active.")
    before = snapshot(assignment)
    assignment.reports_to_user = boss
    if snapshot(assignment) == before:
        return assignment
    _touch(assignment, actor)
    assignment.save()
    _assert_no_reporting_loop(User.objects.filter(pk=assignment.user_id))
    record_updated(actor, assignment, before, metadata={"person": assignment.user.username})
    return assignment


# --- Approval chains -------------------------------------------------------------------


def _describe_step(step: ApprovalHierarchy) -> str:
    if step.approver_type == ApprovalHierarchy.ApproverType.POSITION:
        return f"Position: {step.approver_position.title}"
    if step.approver_type == ApprovalHierarchy.ApproverType.ROLE:
        return f"Role: {step.approver_role.name}"
    if step.approver_type == ApprovalHierarchy.ApproverType.USER:
        return f"Person: {step.approver_user.username}"
    return step.get_approver_type_display()


def chain_steps(department: Department, request_type: str = DEFAULT_REQUEST_TYPE):
    return list(
        ApprovalHierarchy.objects.filter(department=department, request_type=request_type)
        .select_related("approver_position", "approver_role", "approver_user")
        .order_by("step_order")
    )


def _build_step(department: Department, order: int, spec: dict) -> ApprovalHierarchy:
    kind = (spec.get("approver_type") or "").upper()
    if kind not in ApprovalHierarchy.ApproverType.values:
        _invalid("steps", f"Step {order}: choose who approves.")
    kwargs = {"approver_type": kind}
    if kind == "POSITION":
        position = Position.objects.filter(pk=spec.get("position")).first()
        if position is None or position.is_archived:
            _invalid("steps", f"Step {order}: choose a position that is in use.")
        kwargs["approver_position"] = position
    elif kind == "ROLE":
        role = Role.objects.filter(pk=spec.get("role")).first()
        if role is None or not role.is_active:
            _invalid("steps", f"Step {order}: choose a role that is in use.")
        kwargs["approver_role"] = role
    elif kind == "USER":
        person = User.objects.filter(pk=spec.get("user")).first()
        if person is None or person.status != User.Status.ACTIVE:
            _invalid("steps", f"Step {order}: choose a person with an active account.")
        kwargs["approver_user"] = person
    return ApprovalHierarchy(department=department, step_order=order, **kwargs)


@transaction.atomic
def set_approval_chain(
    actor, department: Department, request_type: str, steps: list[dict]
) -> list[ApprovalHierarchy]:
    """Replace a department's chain for one request type. An empty list removes the chain.

    Steps are taken in order: step 1 approves first. Who approves is always resolved by the
    server when a request is submitted (Slice 5); nothing here lets a requester choose.
    """
    _lock_structure()
    department = Department.objects.select_for_update().get(pk=department.pk)
    if department.is_archived:
        _invalid("detail", "This department is archived.")
    request_type = (request_type or "").strip().upper()
    if not REQUEST_TYPE_PATTERN.match(request_type):
        _invalid(
            "request_type", "Use capital letters, digits or underscores, starting with a letter."
        )
    if len(steps) > MAX_CHAIN_STEPS:
        _invalid("steps", f"A chain can have at most {MAX_CHAIN_STEPS} steps.")

    built = [_build_step(department, number, spec) for number, spec in enumerate(steps, start=1)]
    identities = [
        (s.approver_type, s.approver_position_id, s.approver_role_id, s.approver_user_id)
        for s in built
    ]
    if len(set(identities)) != len(identities):
        _invalid("steps", "The same approver cannot appear twice in one chain.")

    old = chain_steps(department, request_type)
    before = [_describe_step(step) for step in old]
    ApprovalHierarchy.objects.filter(department=department, request_type=request_type).delete()
    for step in built:
        step.request_type = request_type
        step.created_by = actor
        step.updated_by = actor
        step.save()
    after = [_describe_step(step) for step in chain_steps(department, request_type)]
    if before != after:
        audit(
            audit_events.RECORD_UPDATED,
            actor=actor,
            object_type=department._meta.label,
            object_id=department.pk,
            department_id=department.pk,
            changes={f"approval_chain.{request_type}": {"from": before, "to": after}},
            metadata={"action": "approval chain changed", "request_type": request_type},
        )
    return chain_steps(department, request_type)


# --- Reading ---------------------------------------------------------------------------


def organisation_tree(*, include_archived: bool = False) -> list[dict]:
    """Departments nested under their parents, each with positions and who holds them.

    Names only: no contact details, so the same payload is safe to cache on a device later.
    """
    departments = Department.objects.select_related("head").order_by("name")
    positions = Position.objects.select_related("reports_to").order_by("title")
    holders = StaffAssignment.objects.filter(end_date__isnull=True).select_related("user")
    if not include_archived:
        departments = departments.filter(is_archived=False)
        positions = positions.filter(is_archived=False)

    holders_by_position: dict = {}
    for assignment in holders.order_by("user__full_name"):
        holders_by_position.setdefault(assignment.position_id, []).append(
            {
                "assignment_id": str(assignment.id),
                "user_id": str(assignment.user_id),
                "full_name": assignment.user.full_name,
                "is_primary": assignment.is_primary,
            }
        )
    positions_by_department: dict = {}
    for position in positions:
        positions_by_department.setdefault(position.department_id, []).append(
            {
                "id": str(position.id),
                "title": position.title,
                "reports_to_id": str(position.reports_to_id) if position.reports_to_id else None,
                "is_department_head_position": position.is_department_head_position,
                "is_archived": position.is_archived,
                "holders": holders_by_position.get(position.id, []),
            }
        )

    people = dict(
        _current_assignments_count()
    )  # {department_id: distinct people currently assigned}
    nodes = {}
    for department in departments:
        nodes[department.id] = {
            "id": str(department.id),
            "code": department.code,
            "name": department.name,
            "description": department.description,
            "parent_id": str(department.parent_id) if department.parent_id else None,
            "head": (
                {"id": str(department.head_id), "full_name": department.head.full_name}
                if department.head_id
                else None
            ),
            "is_archived": department.is_archived,
            "staff_count": people.get(department.id, 0),
            "positions": positions_by_department.get(department.id, []),
            "children": [],
        }
    roots = []
    for department in departments:
        node = nodes[department.id]
        parent = nodes.get(department.parent_id)
        (parent["children"] if parent else roots).append(node)
    return roots


def _current_assignments_count():
    rows = (
        StaffAssignment.objects.filter(end_date__isnull=True)
        .values("department_id")
        .annotate(total=Count("user_id", distinct=True))
    )
    return [(row["department_id"], row["total"]) for row in rows]

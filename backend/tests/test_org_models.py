"""Organisation models: database constraints, the starting structure, sync policy."""

import datetime

import pytest
from django.db import IntegrityError, transaction

from apps.organisation import seed as org_seed
from apps.organisation.models import (
    ApprovalHierarchy,
    Department,
    Position,
    StaffAssignment,
)
from apps.rbac.models import Role

TODAY = datetime.date(2026, 11, 20)


@pytest.fixture
def dept(db):
    return Department.objects.create(code="TESTDEPT", name="Test Department")


@pytest.fixture
def position(dept):
    return Position.objects.create(department=dept, title="Officer")


# --- Starting structure ---


def test_starting_structure_has_a_department_for_each_module(db):
    codes = set(Department.objects.values_list("code", flat=True))
    assert {code for code, *_ in org_seed.DEPARTMENTS} <= codes
    assert len(org_seed.DEPARTMENTS) == 12


def test_every_starting_department_has_one_head_position_and_no_people(db):
    for code, *_ in org_seed.DEPARTMENTS:
        heads = Position.objects.filter(department__code=code, is_department_head_position=True)
        assert heads.count() == 1, code
    assert StaffAssignment.objects.count() == 0  # no invented people
    assert Department.objects.filter(head__isnull=False).count() == 0


def test_heads_report_to_the_executive_director(db):
    director = Position.objects.get(
        department__code="ADMINISTRATION", title=org_seed.EXECUTIVE_DIRECTOR
    )
    assert director.reports_to is None
    others = Position.objects.filter(is_department_head_position=True).exclude(pk=director.pk)
    assert others.count() == 11 and all(p.reports_to_id == director.pk for p in others)


def test_starting_structure_is_flat_and_not_archived(db):
    assert not Department.objects.filter(parent__isnull=False).exists()
    assert not Department.objects.filter(is_archived=True).exists()


def test_reseeding_creates_nothing_and_never_undoes_edits(db):
    Department.objects.filter(code="MEDICAL").update(name="Health Centre")
    Position.objects.filter(department__code="MEDICAL").delete()
    Department.objects.filter(code="STORES").update(is_active=True, description="Mine")

    created = org_seed.seed(Department, Position)

    assert created == 0
    assert Department.objects.get(code="MEDICAL").name == "Health Centre"
    assert not Position.objects.filter(department__code="MEDICAL").exists()  # edits stand
    assert Department.objects.get(code="STORES").description == "Mine"
    assert Department.objects.count() == 12


def test_seed_skips_a_department_whose_name_is_taken(db):
    Position.objects.filter(department__code="FINANCE").delete()
    Department.objects.filter(code="FINANCE").delete()
    Department.objects.create(code="MONEY", name="Finance")
    assert org_seed.seed(Department, Position) == 0
    assert not Department.objects.filter(code="FINANCE").exists()


def test_seed_command_is_repeatable(db, capsys):
    from django.core.management import call_command

    call_command("seed_organisation")
    assert "Created 0 department(s)." in capsys.readouterr().out


# --- Sync policy and sync-ready columns ---------------------------------------------------------


@pytest.mark.parametrize("model", [Department, Position, StaffAssignment, ApprovalHierarchy])
def test_every_model_declares_a_sync_policy_that_never_allows_offline_writes(model):
    policy = model.SYNC_POLICY
    assert {"offline_read", "offline_write", "conflict", "classification"} <= set(policy)
    assert policy["offline_write"] is False  # structure is changed online only
    assert policy["conflict"] == "SERVER_WINS"
    names = {field.name for field in model._meta.get_fields()}
    assert {"version", "updated_by", "created_at", "updated_at"} <= names
    assert model._meta.pk.get_internal_type() == "UUIDField"


def test_chains_are_never_cached_on_devices():
    assert ApprovalHierarchy.SYNC_POLICY["offline_read"] is False
    assert Department.SYNC_POLICY["offline_read"] is True


# --- Department constraints ---


def test_department_code_and_name_are_unique(dept):
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.create(code="TESTDEPT", name="Other")
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.create(code="OTHER", name="Test Department")


def test_a_department_cannot_be_its_own_parent(dept):
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.filter(pk=dept.pk).update(parent=dept)


def test_an_archived_department_must_be_inactive_and_stamped(dept):
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.filter(pk=dept.pk).update(is_archived=True)  # still active, no stamp
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.filter(pk=dept.pk).update(is_archived=True, is_active=False)  # no stamp


# --- Position constraints ---


def test_position_titles_are_unique_within_a_department(dept, position):
    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.create(department=dept, title="Officer")
    other = Department.objects.create(code="OTHER", name="Other")
    Position.objects.create(department=other, title="Officer")  # fine elsewhere


def test_a_position_cannot_report_to_itself(position):
    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.filter(pk=position.pk).update(reports_to=position)


def test_only_one_live_head_position_per_department(dept):
    Position.objects.create(department=dept, title="Head", is_department_head_position=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.create(
            department=dept, title="Deputy head", is_department_head_position=True
        )


# --- Assignment constraints ---


def assignment(user, position, **kwargs):
    return StaffAssignment.objects.create(
        user=user,
        position=position,
        department=position.department,
        start_date=kwargs.pop("start_date", TODAY),
        **kwargs,
    )


def test_one_current_main_assignment_per_person(make_user, dept, position):
    user = make_user("someone")
    second = Position.objects.create(department=dept, title="Clerk")
    assignment(user, position, is_primary=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        assignment(user, second, is_primary=True)
    assignment(user, second, is_primary=False)  # additional assignments are fine


def test_an_ended_main_assignment_does_not_block_a_new_one(make_user, dept, position):
    user = make_user("someone")
    old = assignment(user, position, is_primary=True)
    old.end_date = TODAY
    old.save()
    clerk = Position.objects.create(department=dept, title="Clerk")
    assignment(user, clerk, is_primary=True)


def test_a_person_cannot_hold_the_same_position_twice_at_once(make_user, position):
    user = make_user("someone")
    assignment(user, position)
    with pytest.raises(IntegrityError), transaction.atomic():
        assignment(user, position)


def test_assignment_dates_must_be_in_order(make_user, position):
    user = make_user("someone")
    with pytest.raises(IntegrityError), transaction.atomic():
        assignment(user, position, end_date=TODAY - datetime.timedelta(days=1))


def test_nobody_reports_to_themselves(make_user, position):
    user = make_user("someone")
    with pytest.raises(IntegrityError), transaction.atomic():
        assignment(user, position, reports_to_user=user)


# --- Approval chain constraints ---


def step(dept, **kwargs):
    kwargs.setdefault("request_type", "DEFAULT")
    kwargs.setdefault("step_order", 1)
    return ApprovalHierarchy.objects.create(department=dept, **kwargs)


def test_a_chain_step_names_exactly_what_its_type_needs(dept, position, make_user):
    user = make_user("approver")
    role = Role.objects.get(code="FINANCE_OFFICER")
    step(dept, approver_type="POSITION", approver_position=position, step_order=1)
    step(dept, approver_type="ROLE", approver_role=role, step_order=2)
    step(dept, approver_type="USER", approver_user=user, step_order=3)
    step(dept, approver_type="DEPARTMENT_HEAD", step_order=4)
    step(dept, approver_type="REPORTS_TO", step_order=5)

    bad = [
        {"approver_type": "POSITION"},  # nothing named
        {"approver_type": "POSITION", "approver_position": position, "approver_role": role},
        {"approver_type": "ROLE", "approver_position": position},  # wrong kind of target
        {"approver_type": "DEPARTMENT_HEAD", "approver_user": user},  # head needs no target
        {"approver_type": "USER"},
        {"approver_type": "MANAGER", "approver_user": user},  # unknown type
    ]
    for number, values in enumerate(bad, start=10):
        with pytest.raises(IntegrityError), transaction.atomic():
            step(dept, step_order=number, **values)


def test_chain_step_numbers_are_positive_and_unique(dept):
    step(dept, approver_type="DEPARTMENT_HEAD", step_order=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        step(dept, approver_type="REPORTS_TO", step_order=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        step(dept, approver_type="REPORTS_TO", step_order=0)
    step(dept, approver_type="REPORTS_TO", step_order=1, request_type="LEAVE")  # other type: fine

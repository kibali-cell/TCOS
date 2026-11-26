"""Organisation rules: cycles, archive blocking, assignments, chains, audit."""

import datetime

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.service import verify_chain
from apps.organisation import services
from apps.organisation.models import (
    ApprovalHierarchy,
    Department,
    Position,
    StaffAssignment,
)
from apps.rbac.models import Role


@pytest.fixture
def actor(make_user):
    return make_user("org.admin")


@pytest.fixture
def alpha(actor):
    return services.create_department(actor, code="alpha", name="Alpha")


@pytest.fixture
def beta(actor):
    return services.create_department(actor, code="BETA", name="Beta")


@pytest.fixture
def clerk(actor, alpha):
    return services.create_position(actor, department=alpha, title="Clerk")


@pytest.fixture
def clerk_b(actor, beta):
    return services.create_position(actor, department=beta, title="Clerk")


def events(event_type, object_type=None):
    queryset = AuditEvent.objects.filter(event_type=event_type)
    return queryset.filter(object_type=object_type) if object_type else queryset


def message(error) -> str:
    return " ".join(str(text) for texts in error.value.detail.values() for text in texts)


# --- Departments: create and edit ---


def test_create_department_normalises_the_code_and_is_audited(actor, alpha):
    assert alpha.code == "ALPHA" and alpha.version == 1 and alpha.updated_by == actor
    event = events("RECORD_CREATED", "organisation.Department").get()
    assert event.object_id == str(alpha.pk) and event.actor_id == actor.pk
    assert event.department_id == alpha.pk  # department-scoped audit viewers can see it
    assert event.changes["name"] == {"from": None, "to": "Alpha"}
    assert "updated_at" not in event.changes


@pytest.mark.parametrize("code", ["", "A", "1ABC", "has space", "x" * 41, "DASH-ED"])
def test_a_bad_department_code_is_refused(actor, code):
    with pytest.raises(ValidationError):
        services.create_department(actor, code=code, name="Whatever")
    assert not Department.objects.filter(name="Whatever").exists()


def test_duplicate_names_and_codes_are_refused_ignoring_case(actor, alpha):
    with pytest.raises(ValidationError):
        services.create_department(actor, code="OTHER", name="alpha")
    with pytest.raises(ValidationError):
        services.create_department(actor, code="alpha", name="Different")
    with pytest.raises(ValidationError):
        services.create_department(actor, code="OTHER", name="   ")


def test_update_department_bumps_the_version_and_records_only_what_changed(actor, alpha):
    services.update_department(actor, alpha, name="Alpha Renamed", description="About")
    alpha.refresh_from_db()
    assert alpha.name == "Alpha Renamed" and alpha.version == 2
    event = events("RECORD_UPDATED", "organisation.Department").get()
    assert set(event.changes) == {"name", "description", "version"}
    assert event.changes["name"] == {"from": "Alpha", "to": "Alpha Renamed"}


def test_an_update_that_changes_nothing_writes_nothing(actor, alpha):
    services.update_department(actor, alpha, name="Alpha")
    alpha.refresh_from_db()
    assert alpha.version == 1 and not events("RECORD_UPDATED").exists()


def test_a_rename_cannot_take_another_departments_name(actor, alpha, beta):
    with pytest.raises(ValidationError):
        services.update_department(actor, alpha, name="beta")


# --- Departments: no cycles ---


def test_a_department_cannot_be_its_own_parent(actor, alpha):
    with pytest.raises(ValidationError) as error:
        services.update_department(actor, alpha, parent=alpha)
    assert "cannot sit under itself" in message(error)


def test_departments_cannot_form_a_loop_however_long(actor, alpha, beta):
    gamma = services.create_department(actor, code="GAMMA", name="Gamma", parent=beta)
    services.update_department(actor, beta, parent=alpha)  # alpha > beta > gamma
    with pytest.raises(ValidationError):
        services.update_department(actor, alpha, parent=gamma)  # would close the loop
    with pytest.raises(ValidationError):
        services.update_department(actor, alpha, parent=beta)
    alpha.refresh_from_db()
    assert alpha.parent_id is None


def test_a_department_can_move_to_a_valid_parent_and_back(actor, alpha, beta):
    services.update_department(actor, beta, parent=alpha)
    services.update_department(actor, beta, parent=None)
    beta.refresh_from_db()
    assert beta.parent_id is None and beta.version == 3


def test_an_archived_department_cannot_be_a_parent(actor, alpha, beta):
    services.archive_department(actor, beta)
    with pytest.raises(ValidationError):
        services.update_department(actor, alpha, parent=beta)
    with pytest.raises(ValidationError):
        services.create_department(actor, code="KID", name="Kid", parent=beta)


# --- Positions ---


def test_create_position_is_audited_with_its_department(actor, alpha, clerk):
    event = events("RECORD_CREATED", "organisation.Position").get()
    assert event.department_id == alpha.pk and event.changes["title"]["to"] == "Clerk"


def test_position_titles_are_unique_per_department_ignoring_case(actor, alpha, beta, clerk):
    with pytest.raises(ValidationError):
        services.create_position(actor, department=alpha, title="CLERK")
    services.create_position(actor, department=beta, title="Clerk")  # a different department


def test_a_position_can_report_to_one_in_another_department(actor, clerk, clerk_b):
    services.update_position(actor, clerk, reports_to=clerk_b)
    clerk.refresh_from_db()
    assert clerk.reports_to_id == clerk_b.pk


def test_positions_cannot_report_in_a_circle(actor, alpha):
    a = services.create_position(actor, department=alpha, title="A")
    b = services.create_position(actor, department=alpha, title="B", reports_to=a)
    c = services.create_position(actor, department=alpha, title="C", reports_to=b)
    with pytest.raises(ValidationError) as error:
        services.update_position(actor, a, reports_to=c)
    assert "cannot report to itself" in message(error)
    with pytest.raises(ValidationError):
        services.update_position(actor, a, reports_to=a)
    a.refresh_from_db()
    assert a.reports_to_id is None


def test_a_department_has_at_most_one_head_position(actor, alpha):
    services.create_position(
        actor, department=alpha, title="Head", is_department_head_position=True
    )
    with pytest.raises(ValidationError):
        services.create_position(
            actor, department=alpha, title="Deputy", is_department_head_position=True
        )
    deputy = services.create_position(actor, department=alpha, title="Deputy")
    with pytest.raises(ValidationError):
        services.update_position(actor, deputy, is_department_head_position=True)


def test_a_position_cannot_be_created_in_an_archived_department(actor, beta):
    services.archive_department(actor, beta)
    with pytest.raises(ValidationError):
        services.create_position(actor, department=beta, title="Late")


# --- Staff assignments: the main assignment drives the department ---


def test_the_first_assignment_is_main_and_sets_the_persons_department(
    actor, make_user, alpha, clerk
):
    user = make_user("worker")
    assignment = services.assign_staff(actor, user, clerk)
    user.refresh_from_db()
    assert assignment.is_primary and assignment.department_id == alpha.pk
    assert user.department_id == alpha.pk
    assert assignment.start_date == timezone.localdate()
    created = events("RECORD_CREATED", "organisation.StaffAssignment").get()
    assert created.department_id == alpha.pk and created.metadata["person"] == "worker"
    moved = events("USER_UPDATED").get()
    assert moved.changes["department_id"] == {"from": None, "to": str(alpha.pk)}
    assert moved.metadata["source"] == "main staff assignment"


def test_an_additional_assignment_leaves_the_department_alone(actor, make_user, clerk, clerk_b):
    user = make_user("worker")
    services.assign_staff(actor, user, clerk)
    extra = services.assign_staff(actor, user, clerk_b)
    user.refresh_from_db()
    assert extra.is_primary is False and user.department_id == clerk.department_id


def test_a_second_main_assignment_is_refused_with_advice(actor, make_user, clerk, clerk_b):
    user = make_user("worker")
    services.assign_staff(actor, user, clerk)
    with pytest.raises(ValidationError) as error:
        services.assign_staff(actor, user, clerk_b, is_primary=True)
    assert "Transfer" in message(error)
    assert StaffAssignment.objects.filter(user=user).count() == 1


def test_assignment_refusals(actor, make_user, alpha, clerk):
    user = make_user("worker")
    services.assign_staff(actor, user, clerk)
    with pytest.raises(ValidationError):  # already holds it
        services.assign_staff(actor, user, clerk)
    inactive = make_user("gone", status="INACTIVE")
    with pytest.raises(ValidationError):
        services.assign_staff(actor, inactive, clerk)
    future = timezone.localdate() + datetime.timedelta(days=1)
    other = make_user("other")
    with pytest.raises(ValidationError):
        services.assign_staff(actor, other, clerk, start_date=future)
    services.archive_position(actor, services.create_position(actor, department=alpha, title="Old"))
    with pytest.raises(ValidationError):
        services.assign_staff(actor, other, Position.objects.get(title="Old"))


def test_transfer_moves_the_person_and_keeps_history(actor, make_user, clerk, clerk_b, beta):
    user = make_user("worker")
    first = services.assign_staff(actor, user, clerk)

    second = services.transfer_staff(actor, first, clerk_b)

    user.refresh_from_db()
    first.refresh_from_db()
    assert user.department_id == beta.pk
    assert first.end_date == timezone.localdate() and second.is_primary and second.is_current
    assert StaffAssignment.objects.filter(user=user).count() == 2  # history kept
    assert [e.changes["department_id"]["to"] for e in events("USER_UPDATED").order_by("id")][
        -1
    ] == str(beta.pk)


def test_transfer_to_the_same_position_is_refused(actor, make_user, clerk):
    first = services.assign_staff(actor, make_user("worker"), clerk)
    with pytest.raises(ValidationError):
        services.transfer_staff(actor, first, clerk)


def test_ending_the_main_assignment_clears_the_department(actor, make_user, clerk):
    user = make_user("worker")
    assignment = services.assign_staff(actor, user, clerk)
    services.end_assignment(actor, assignment)
    user.refresh_from_db()
    assert user.department_id is None
    with pytest.raises(ValidationError):  # cannot end twice
        services.end_assignment(actor, assignment)


def test_ending_an_additional_assignment_keeps_the_department(actor, make_user, clerk, clerk_b):
    user = make_user("worker")
    services.assign_staff(actor, user, clerk)
    extra = services.assign_staff(actor, user, clerk_b)
    services.end_assignment(actor, extra)
    user.refresh_from_db()
    assert user.department_id == clerk.department_id


def test_end_dates_are_checked(actor, make_user, clerk):
    assignment = services.assign_staff(actor, make_user("worker"), clerk)
    with pytest.raises(ValidationError):
        services.end_assignment(
            actor, assignment, end_date=timezone.localdate() + datetime.timedelta(days=1)
        )
    with pytest.raises(ValidationError):
        services.end_assignment(
            actor, assignment, end_date=assignment.start_date - datetime.timedelta(days=1)
        )


def test_make_primary_swaps_and_changes_the_department(actor, make_user, clerk, clerk_b, beta):
    user = make_user("worker")
    first = services.assign_staff(actor, user, clerk)
    second = services.assign_staff(actor, user, clerk_b)

    services.make_primary(actor, second)

    for item in (user, first, second):
        item.refresh_from_db()
    assert second.is_primary and not first.is_primary and first.is_current
    assert user.department_id == beta.pk


def test_a_person_without_a_main_assignment_keeps_the_department_empty(
    actor, make_user, clerk, clerk_b
):
    user = make_user("worker")
    main = services.assign_staff(actor, user, clerk)
    services.assign_staff(actor, user, clerk_b)
    services.end_assignment(actor, main)
    user.refresh_from_db()
    assert user.department_id is None and user.staff_assignments.filter(end_date=None).count() == 1


# --- Department head ---


def test_a_head_must_work_in_the_department_and_be_active(actor, make_user, alpha, clerk, clerk_b):
    outsider = make_user("outsider")
    services.assign_staff(actor, outsider, clerk_b)
    with pytest.raises(ValidationError) as error:
        services.set_department_head(actor, alpha, outsider)
    assert "hold a position in the department" in message(error)

    insider = make_user("insider")
    services.assign_staff(actor, insider, clerk)
    services.set_department_head(actor, alpha, insider)
    alpha.refresh_from_db()
    assert alpha.head_id == insider.pk and alpha.version == 2

    services.set_department_head(actor, alpha, None)
    alpha.refresh_from_db()
    assert alpha.head_id is None


def test_when_the_head_leaves_the_post_is_cleared_and_recorded(actor, make_user, alpha, clerk):
    head = make_user("head")
    assignment = services.assign_staff(actor, head, clerk)
    services.set_department_head(actor, alpha, head)

    services.end_assignment(actor, assignment)

    alpha.refresh_from_db()
    assert alpha.head_id is None
    cleared = events("RECORD_UPDATED", "organisation.Department").order_by("id").last()
    assert cleared.metadata["reason"] == "head left the department"


def test_the_head_stays_if_they_still_hold_another_position_there(actor, make_user, alpha, clerk):
    head = make_user("head")
    first = services.assign_staff(actor, head, clerk)
    second_position = services.create_position(actor, department=alpha, title="Auditor")
    services.assign_staff(actor, head, second_position)
    services.set_department_head(actor, alpha, head)
    services.end_assignment(actor, first)
    alpha.refresh_from_db()
    assert alpha.head_id == head.pk


# --- Reporting lines between people: no cycles ---


def test_override_reporting_lines_cannot_loop(actor, make_user, clerk, clerk_b):
    ann, bob = make_user("ann"), make_user("bob")
    a = services.assign_staff(actor, ann, clerk, reports_to_user=bob)
    b = services.assign_staff(actor, bob, clerk_b)
    with pytest.raises(ValidationError) as error:
        services.set_reports_to_user(actor, b, ann)
    assert "report, in the end, to themselves" in message(error)
    b.refresh_from_db()
    assert b.reports_to_user_id is None and a.reports_to_user_id == bob.pk
    with pytest.raises(ValidationError):
        services.set_reports_to_user(actor, a, ann)


def test_a_loop_through_position_reporting_lines_is_caught_too(actor, make_user, alpha):
    boss_position = services.create_position(actor, department=alpha, title="Boss")
    staff_position = services.create_position(
        actor, department=alpha, title="Staff", reports_to=boss_position
    )
    boss, staff = make_user("boss"), make_user("staff")
    services.assign_staff(actor, staff, staff_position)
    boss_assignment = services.assign_staff(actor, boss, boss_position)
    with pytest.raises(ValidationError):  # staff reports (by position) to boss
        services.set_reports_to_user(actor, boss_assignment, staff)


def test_changing_a_position_line_cannot_create_a_person_loop(actor, make_user, alpha):
    first = services.create_position(actor, department=alpha, title="First")
    second = services.create_position(actor, department=alpha, title="Second", reports_to=first)
    ann, bob = make_user("ann"), make_user("bob")
    services.assign_staff(actor, ann, first)
    services.assign_staff(actor, bob, second)  # bob reports to ann by position
    with pytest.raises(ValidationError):
        services.update_position(actor, first, reports_to=second)  # also a position loop


def test_a_reporting_override_needs_an_active_other_person(actor, make_user, clerk):
    assignment = services.assign_staff(actor, make_user("worker"), clerk)
    with pytest.raises(ValidationError):
        services.set_reports_to_user(actor, assignment, assignment.user)
    with pytest.raises(ValidationError):
        services.set_reports_to_user(actor, assignment, make_user("gone", status="INACTIVE"))
    boss = make_user("boss")
    services.set_reports_to_user(actor, assignment, boss)
    assignment.refresh_from_db()
    assert assignment.reports_to_user_id == boss.pk and assignment.version == 2
    services.set_reports_to_user(actor, assignment, None)


# --- Archiving is blocked while anything depends on the record ---


def test_a_department_with_people_cannot_be_archived(actor, make_user, alpha, clerk):
    user = make_user("worker")
    services.assign_staff(actor, user, clerk)
    with pytest.raises(ValidationError) as error:
        services.archive_department(actor, alpha)
    text = message(error)
    assert "cannot be archived yet" in text and "1 person still works in it" in text
    alpha.refresh_from_db()
    assert not alpha.is_archived and not events("RECORD_ARCHIVED").exists()


def test_the_reason_counts_people_and_lists_every_blocker(actor, make_user, alpha, beta, clerk):
    services.update_department(actor, beta, parent=alpha)
    for name in ("one", "two"):
        services.assign_staff(actor, make_user(name), clerk)
    with pytest.raises(ValidationError) as error:
        services.archive_department(actor, alpha)
    text = message(error)
    assert "1 active sub-department" in text and "2 people still work in it" in text
    assert services.department_blockers(alpha) and len(services.department_blockers(alpha)) == 2


def test_active_users_whose_department_is_set_also_block_archiving(actor, make_user, alpha):
    make_user("fixture.user", department=alpha)
    with pytest.raises(ValidationError):
        services.archive_department(actor, alpha)


def test_other_departments_depending_on_it_block_archiving(actor, alpha, beta, clerk, clerk_b):
    services.update_position(actor, clerk_b, reports_to=clerk)
    with pytest.raises(ValidationError) as error:
        services.archive_department(actor, alpha)
    assert "report to its positions" in message(error)
    services.update_position(actor, clerk_b, reports_to=None)
    services.set_approval_chain(
        actor, beta, "DEFAULT", [{"approver_type": "POSITION", "position": str(clerk.pk)}]
    )
    with pytest.raises(ValidationError) as error:
        services.archive_department(actor, alpha)
    assert "approval step" in message(error)


def test_later_slices_can_add_their_own_blockers(actor, alpha, monkeypatch):
    monkeypatch.setattr(
        services, "ARCHIVE_BLOCKERS", [lambda department: "3 requests are still open"]
    )
    with pytest.raises(ValidationError) as error:
        services.archive_department(actor, alpha)
    assert "3 requests are still open" in message(error)


def test_an_empty_department_archives_with_its_positions_and_chain(actor, make_user, alpha, clerk):
    services.set_approval_chain(actor, alpha, "DEFAULT", [{"approver_type": "DEPARTMENT_HEAD"}])

    services.archive_department(actor, alpha, reason="Merged into Beta")

    alpha.refresh_from_db()
    clerk.refresh_from_db()
    assert alpha.is_archived and not alpha.is_active and alpha.archived_by_id == actor.pk
    assert clerk.is_archived and not clerk.is_active
    assert not ApprovalHierarchy.objects.filter(department=alpha, is_active=True).exists()
    event = events("RECORD_ARCHIVED", "organisation.Department").get()
    assert event.metadata["reason"] == "Merged into Beta"
    assert event.metadata["archived_positions"] == ["Clerk"]
    assert services.archive_department(actor, alpha).is_archived  # idempotent


def test_an_archived_department_cannot_be_edited_staffed_or_given_chains(
    actor, make_user, alpha, clerk
):
    services.archive_department(actor, alpha)
    with pytest.raises(ValidationError):
        services.update_department(actor, alpha, name="Changed")
    with pytest.raises(ValidationError):
        services.set_approval_chain(actor, alpha, "DEFAULT", [])
    with pytest.raises(ValidationError):
        services.assign_staff(actor, make_user("worker"), clerk)


def test_restoring_a_department_leaves_its_positions_archived(actor, alpha, clerk):
    services.archive_department(actor, alpha)
    services.restore_department(actor, alpha)
    alpha.refresh_from_db()
    clerk.refresh_from_db()
    assert alpha.is_active and not alpha.is_archived and alpha.archived_at is None
    assert clerk.is_archived  # restored one by one, on purpose
    services.restore_position(actor, clerk)
    clerk.refresh_from_db()
    assert not clerk.is_archived
    assert events("RECORD_UPDATED").filter(metadata__action="restored").count() == 2


def test_a_department_cannot_be_restored_under_an_archived_parent(actor, alpha, beta):
    services.update_department(actor, beta, parent=alpha)
    services.archive_department(actor, beta)
    services.archive_department(actor, alpha)
    with pytest.raises(ValidationError):
        services.restore_department(actor, beta)


def test_a_position_with_a_holder_reports_or_chain_cannot_be_archived(
    actor, make_user, alpha, beta, clerk, clerk_b
):
    services.assign_staff(actor, make_user("worker"), clerk)
    with pytest.raises(ValidationError) as error:
        services.archive_position(actor, clerk)
    assert "1 person currently holds it" in message(error)

    services.update_position(actor, clerk_b, reports_to=clerk)
    assert any("report to it" in reason for reason in services.position_blockers(clerk))

    services.set_approval_chain(
        actor, beta, "DEFAULT", [{"approver_type": "POSITION", "position": str(clerk.pk)}]
    )
    assert any("approval step" in reason for reason in services.position_blockers(clerk))
    clerk.refresh_from_db()
    assert not clerk.is_archived


def test_a_free_position_archives_and_restores(actor, alpha):
    position = services.create_position(actor, department=alpha, title="Temp")
    services.archive_position(actor, position, reason="Not needed")
    position.refresh_from_db()
    assert position.is_archived
    with pytest.raises(ValidationError):
        services.update_position(actor, position, title="Edited")
    services.restore_position(actor, position)
    position.refresh_from_db()
    assert position.is_active and not position.is_archived


def test_a_position_cannot_be_restored_into_an_archived_department(actor, alpha, clerk):
    services.archive_department(actor, alpha)
    with pytest.raises(ValidationError):
        services.restore_position(actor, clerk)


# --- Approval chains ---


def test_a_chain_of_every_kind_is_stored_in_order(actor, make_user, alpha, clerk):
    approver = make_user("approver")
    role = Role.objects.get(code="FINANCE_OFFICER")
    steps = services.set_approval_chain(
        actor,
        alpha,
        "purchase",
        [
            {"approver_type": "REPORTS_TO"},
            {"approver_type": "POSITION", "position": str(clerk.pk)},
            {"approver_type": "ROLE", "role": str(role.pk)},
            {"approver_type": "USER", "user": str(approver.pk)},
            {"approver_type": "DEPARTMENT_HEAD"},
        ],
    )
    assert [s.step_order for s in steps] == [1, 2, 3, 4, 5]
    assert [s.approver_type for s in steps] == [
        "REPORTS_TO",
        "POSITION",
        "ROLE",
        "USER",
        "DEPARTMENT_HEAD",
    ]
    assert {s.request_type for s in steps} == {"PURCHASE"}  # normalised
    event = events("RECORD_UPDATED", "organisation.Department").get()
    assert event.changes["approval_chain.PURCHASE"]["to"][1] == "Position: Clerk"
    assert event.changes["approval_chain.PURCHASE"]["from"] == []


def test_replacing_a_chain_records_before_and_after(actor, alpha):
    services.set_approval_chain(actor, alpha, "DEFAULT", [{"approver_type": "DEPARTMENT_HEAD"}])
    services.set_approval_chain(actor, alpha, "DEFAULT", [{"approver_type": "REPORTS_TO"}])
    event = events("RECORD_UPDATED").order_by("id").last()
    change = event.changes["approval_chain.DEFAULT"]
    assert change["from"] == ["The department head"]
    assert change["to"] == ["The requester's line manager"]
    assert ApprovalHierarchy.objects.filter(department=alpha).count() == 1


def test_saving_the_same_chain_again_writes_nothing(actor, alpha):
    chain = [{"approver_type": "DEPARTMENT_HEAD"}]
    services.set_approval_chain(actor, alpha, "DEFAULT", chain)
    before = AuditEvent.objects.count()
    services.set_approval_chain(actor, alpha, "DEFAULT", chain)
    assert AuditEvent.objects.count() == before


def test_an_empty_list_removes_the_chain_and_types_are_independent(actor, alpha):
    services.set_approval_chain(actor, alpha, "DEFAULT", [{"approver_type": "DEPARTMENT_HEAD"}])
    services.set_approval_chain(actor, alpha, "LEAVE", [{"approver_type": "REPORTS_TO"}])
    services.set_approval_chain(actor, alpha, "LEAVE", [])
    assert not ApprovalHierarchy.objects.filter(request_type="LEAVE").exists()
    assert ApprovalHierarchy.objects.filter(request_type="DEFAULT").count() == 1


def test_chain_validation(actor, make_user, alpha, clerk):
    role = Role.objects.get(code="FINANCE_OFFICER")
    gone = make_user("gone", status="INACTIVE")
    off = Role.objects.create(code="OFF", name="Off", is_active=False)
    archived = services.create_position(actor, department=alpha, title="Retired")
    services.archive_position(actor, archived)
    bad_chains = [
        [{"approver_type": "MANAGER"}],
        [{"approver_type": "POSITION"}],  # names nothing
        [{"approver_type": "POSITION", "position": str(archived.pk)}],
        [{"approver_type": "ROLE", "role": str(off.pk)}],
        [{"approver_type": "USER", "user": str(gone.pk)}],
        [{"approver_type": "ROLE", "role": str(role.pk)}] * 2,  # same approver twice
        [{"approver_type": "DEPARTMENT_HEAD"}] * 2,
        [{"approver_type": "REPORTS_TO"}] * 7,  # too long
    ]
    for chain in bad_chains:
        with pytest.raises(ValidationError):
            services.set_approval_chain(actor, alpha, "DEFAULT", chain)
    for bad_type in ("", "1ABC", "has space", "x" * 41):
        with pytest.raises(ValidationError):
            services.set_approval_chain(actor, alpha, bad_type, [])
    assert not ApprovalHierarchy.objects.exists()  # a refused chain changes nothing


def test_a_refused_chain_keeps_the_old_one(actor, alpha):
    services.set_approval_chain(actor, alpha, "DEFAULT", [{"approver_type": "DEPARTMENT_HEAD"}])
    with pytest.raises(ValidationError):
        services.set_approval_chain(
            actor, alpha, "DEFAULT", [{"approver_type": "REPORTS_TO"}, {"approver_type": "NOPE"}]
        )
    assert list(
        ApprovalHierarchy.objects.filter(department=alpha).values_list("approver_type", flat=True)
    ) == ["DEPARTMENT_HEAD"]


# --- Audit: complete, atomic, and free of secrets ---


def test_every_structure_change_leaves_exactly_one_event(actor, make_user, alpha, clerk):
    before = AuditEvent.objects.count()
    user = make_user("worker")  # one USER_CREATED event
    services.assign_staff(actor, user, clerk)  # created + user department
    services.set_department_head(actor, alpha, user)  # updated
    services.update_position(actor, clerk, title="Senior Clerk")  # updated
    assert AuditEvent.objects.count() - before == 5


def test_a_failed_audit_write_undoes_the_change(actor, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr("apps.audit.changes.write_event", broken)
    with pytest.raises(RuntimeError):
        services.create_department(actor, code="LOST", name="Lost")
    assert not Department.objects.filter(code="LOST").exists()


def test_a_failed_audit_write_undoes_an_assignment(actor, make_user, clerk, monkeypatch):
    user = make_user("worker")
    monkeypatch.setattr(
        "apps.audit.changes.write_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    with pytest.raises(RuntimeError):
        services.assign_staff(actor, user, clerk)
    user.refresh_from_db()
    assert user.department_id is None and not StaffAssignment.objects.exists()


def test_the_chain_stays_intact_after_a_whole_workflow(
    actor, make_user, alpha, beta, clerk, clerk_b
):
    worker = make_user("worker")
    first = services.assign_staff(actor, worker, clerk)
    services.transfer_staff(actor, first, clerk_b)
    services.set_approval_chain(actor, beta, "DEFAULT", [{"approver_type": "REPORTS_TO"}])
    services.update_department(actor, alpha, parent=beta)
    assert verify_chain()["ok"]


def test_the_tree_shows_names_only_and_nests_departments(actor, make_user, alpha, beta, clerk):
    services.update_department(actor, beta, parent=alpha)
    person = make_user("worker", full_name="Worker One")
    services.assign_staff(actor, person, clerk)

    roots = services.organisation_tree()

    root = next(node for node in roots if node["code"] == "ALPHA")
    assert [child["code"] for child in root["children"]] == ["BETA"]
    holder = root["positions"][0]["holders"][0]
    assert set(holder) == {"assignment_id", "user_id", "full_name", "is_primary"}
    assert holder["full_name"] == "Worker One" and root["staff_count"] == 1
    assert User.objects.get(username="worker").email not in str(roots)


def test_archived_departments_are_left_out_of_the_tree_unless_asked(actor, alpha):
    services.archive_department(actor, alpha)
    assert all(node["code"] != "ALPHA" for node in services.organisation_tree())
    assert any(n["code"] == "ALPHA" for n in services.organisation_tree(include_archived=True))

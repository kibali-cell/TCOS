"""The organisation API: who may use it, the main flows, and the link to scoped access."""

import json

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.organisation import services
from apps.organisation.models import Department, Position, StaffAssignment
from apps.rbac.models import Permission, Role, RolePermission, UserRole

from .conftest import delete, patch, post, put, sign_in
from .rbac_testapp.models import Record
from .test_rbac_management import make_role

BASE = "/api/v1/organisation/"
ALL_ROLES = [
    "BOARD_MEMBER",
    "EXECUTIVE_DIRECTOR",
    "ADMINISTRATOR",
    "SOCIAL_WELFARE_OFFICER",
    "EDUCATION_OFFICER",
    "MEDICAL_OFFICER",
    "FINANCE_OFFICER",
    "PROJECT_MANAGER",
    "STOREKEEPER",
    "PROCUREMENT_OFFICER",
    "HR_OFFICER",
]
CAN_VIEW = {"BOARD_MEMBER", "EXECUTIVE_DIRECTOR", "ADMINISTRATOR"}
CAN_CREATE = {"EXECUTIVE_DIRECTOR", "ADMINISTRATOR"}
CAN_ARCHIVE = {"ADMINISTRATOR"}
READ_URLS = ["tree/", "options/", "people/", "departments/", "positions/", "assignments/"]


def with_role(make_user, new_client, role, username):
    user = make_user(username)
    UserRole.objects.create(user=user, role=role)
    client = new_client()
    assert sign_in(client, username).status_code == 200
    return user, client


@pytest.fixture
def admin(staff):
    return staff("ADMINISTRATOR", username="org.boss")


@pytest.fixture
def world(admin):
    """Two departments with positions, created through the services (as the owner would)."""
    actor = admin[0]
    alpha = services.create_department(actor, code="ALPHA", name="Alpha")
    beta = services.create_department(actor, code="BETA", name="Beta")
    return {
        "alpha": alpha,
        "beta": beta,
        "clerk_a": services.create_position(actor, department=alpha, title="Clerk"),
        "clerk_b": services.create_position(actor, department=beta, title="Clerk"),
    }


def results(response):
    assert response.status_code == 200, response.content
    return response.json()["results"]


def error_text(response) -> str:
    return json.dumps(response.json()["error"])


# --- Who may use it ---


def test_anonymous_users_get_401_everywhere(new_client):
    for url in READ_URLS:
        assert new_client().get(BASE + url).status_code == 401, url
    assert new_client().post(BASE + "departments/", {}, format="json").status_code in (401, 403)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_each_default_role_may_read_only_if_it_should(staff, role):
    _, client = staff(role)
    expected = 200 if role in CAN_VIEW else 403
    for url in READ_URLS:
        assert client.get(BASE + url).status_code == expected, (role, url)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_each_default_role_may_create_only_if_it_should(staff, role):
    _, client = staff(role)
    response = post(client, BASE + "departments/", {"code": f"NEW_{role}"[:40], "name": role})
    assert response.status_code == (201 if role in CAN_CREATE else 403), (role, response.content)
    assert Department.objects.filter(name=role).exists() == (role in CAN_CREATE)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_only_the_administrator_may_archive(staff, world, role):
    _, client = staff(role)
    response = post(client, f"{BASE}departments/{world['beta'].pk}/archive/")
    assert response.status_code == (200 if role in CAN_ARCHIVE else 403), role
    world["beta"].refresh_from_db()
    assert world["beta"].is_archived == (role in CAN_ARCHIVE)


def test_the_board_member_can_look_but_not_touch(staff, world):
    _, client = staff("BOARD_MEMBER")
    pk = world["alpha"].pk
    assert client.get(f"{BASE}departments/{pk}/").status_code == 200
    assert patch(client, f"{BASE}departments/{pk}/", {"name": "Hacked"}).status_code == 403
    assert put(client, f"{BASE}departments/{pk}/head/", {"user": None}).status_code == 403
    assert (
        put(client, f"{BASE}departments/{pk}/approval-chains/DEFAULT/", {"steps": []}).status_code
        == 403
    )
    assert (
        post(client, f"{BASE}positions/", {"department": str(pk), "title": "X"}).status_code == 403
    )
    world["alpha"].refresh_from_db()
    assert world["alpha"].name == "Alpha"


def test_a_department_limited_grant_is_not_enough(make_user, new_client, world):
    """Structure is institution-wide: the permission must be at ALL scope."""
    role = make_role(("administration", "VIEW", "DEPARTMENT"), ("administration", "EDIT", "OWN"))
    _, client = with_role(make_user, new_client, role, "limited")
    assert client.get(BASE + "departments/").status_code == 403
    assert (
        patch(client, f"{BASE}departments/{world['alpha'].pk}/", {"name": "x"}).status_code == 403
    )


def test_a_custom_role_can_be_given_just_the_rights_it_needs(make_user, new_client, world):
    role = make_role(("administration", "VIEW", "ALL"), ("administration", "EDIT", "ALL"))
    _, client = with_role(make_user, new_client, role, "editor")
    pk = world["alpha"].pk
    assert patch(client, f"{BASE}departments/{pk}/", {"description": "Edited"}).status_code == 200
    assert post(client, f"{BASE}departments/", {"code": "NOPE", "name": "Nope"}).status_code == 403
    assert post(client, f"{BASE}departments/{pk}/archive/").status_code == 403


def test_a_forced_password_change_blocks_the_api(make_user, new_client):
    user = make_user("fresh", must_change_password=True)
    UserRole.objects.create(user=user, role=Role.objects.get(code="ADMINISTRATOR"))
    client = new_client()
    sign_in(client, "fresh")
    assert client.get(BASE + "tree/").status_code == 403


def test_a_refusal_reveals_nothing(staff, world):
    _, client = staff("FINANCE_OFFICER")
    response = client.get(BASE + "departments/")
    assert response.status_code == 403 and "Alpha" not in response.content.decode()


def test_writes_need_the_csrf_token(admin, world):
    _, client = admin
    client.get("/api/v1/csrf/")
    response = client.post(BASE + "departments/", {"code": "X1", "name": "X"}, format="json")
    assert response.status_code == 403
    assert not Department.objects.filter(code="X1").exists()


def test_there_is_no_hard_delete(admin, world):
    _, client = admin
    for url in (
        f"{BASE}departments/{world['alpha'].pk}/",
        f"{BASE}positions/{world['clerk_a'].pk}/",
        f"{BASE}assignments/{world['clerk_a'].pk}/",
    ):
        assert delete(client, url).status_code in (404, 405), url
    assert Department.objects.filter(pk=world["alpha"].pk).exists()


# --- Departments ---


def test_create_edit_and_read_a_department(admin):
    _, client = admin
    created = post(
        client, BASE + "departments/", {"code": "laundry", "name": "Laundry", "description": "Wash"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["code"] == "LAUNDRY" and body["version"] == 1 and body["parent"] is None
    assert body["staff_count"] == 0 and body["position_count"] == 0

    pk = body["id"]
    changed = patch(client, f"{BASE}departments/{pk}/", {"name": "Laundry and Linen"})
    assert changed.status_code == 200 and changed.json()["version"] == 2
    detail = client.get(f"{BASE}departments/{pk}/").json()
    assert detail["name"] == "Laundry and Linen" and detail["archive_blockers"] == []


def test_validation_errors_use_the_standard_envelope(admin, world):
    _, client = admin
    for payload in (
        {"code": "alpha", "name": "Fresh Name"},
        {"code": "FRESH", "name": "alpha"},
        {"code": "1BAD", "name": "Bad"},
        {"code": "OK", "name": ""},
        {},
    ):
        response = post(client, BASE + "departments/", payload)
        assert response.status_code == 400, payload
        assert response.json()["error"]["code"] == "validation_error"


def test_the_code_cannot_be_changed_through_the_api(admin, world):
    _, client = admin
    response = patch(client, f"{BASE}departments/{world['alpha'].pk}/", {"code": "CHANGED"})
    assert response.status_code == 200
    world["alpha"].refresh_from_db()
    assert world["alpha"].code == "ALPHA" and world["alpha"].version == 1


def test_unknown_ids_are_404(admin):
    _, client = admin
    missing = "6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11"
    for url in (
        f"departments/{missing}/",
        f"positions/{missing}/",
        f"assignments/{missing}/",
        f"departments/{missing}/approval-chains/",
    ):
        assert client.get(BASE + url).status_code == 404, url
    assert post(client, f"{BASE}departments/{missing}/archive/").status_code == 404


def test_department_list_search_filters_and_paging(admin, world):
    _, client = admin
    actor = admin[0]
    services.update_department(actor, world["beta"], parent=world["alpha"])
    services.archive_department(
        actor, services.create_department(actor, code="OLD", name="Old Dept")
    )

    names = {d["name"] for d in results(client.get(BASE + "departments/", {"q": "alph"}))}
    assert names == {"Alpha"}
    assert {d["code"] for d in results(client.get(BASE + "departments/", {"q": "BET"}))} == {"BETA"}
    children = results(client.get(BASE + "departments/", {"parent": str(world["alpha"].pk)}))
    assert [d["code"] for d in children] == ["BETA"]
    assert "ALPHA" in {
        d["code"] for d in results(client.get(BASE + "departments/", {"parent": "none"}))
    }
    assert "OLD" not in {d["code"] for d in results(client.get(BASE + "departments/"))}  # hidden
    assert {
        d["code"] for d in results(client.get(BASE + "departments/", {"archived": "true"}))
    } == {"OLD"}
    assert "OLD" in {
        d["code"] for d in results(client.get(BASE + "departments/", {"archived": "all"}))
    }

    page = client.get(BASE + "departments/", {"page_size": 5}).json()
    assert len(page["results"]) == 5 and page["count"] >= 14 and page["next"]


def test_moving_a_department_under_its_own_child_is_refused(admin, world):
    _, client = admin
    services.update_department(admin[0], world["beta"], parent=world["alpha"])
    response = patch(
        client, f"{BASE}departments/{world['alpha'].pk}/", {"parent": str(world["beta"].pk)}
    )
    assert response.status_code == 400 and "sub-departments" in error_text(response)


def test_archiving_with_people_is_blocked_with_a_clear_message(admin, make_user, world):
    _, client = admin
    services.assign_staff(admin[0], make_user("worker"), world["clerk_a"])
    response = post(client, f"{BASE}departments/{world['alpha'].pk}/archive/", {"reason": "x"})
    assert response.status_code == 400
    text = error_text(response)
    assert "cannot be archived yet" in text and "1 person still works in it" in text
    detail = client.get(f"{BASE}departments/{world['alpha'].pk}/").json()
    assert len(detail["archive_blockers"]) == 1  # the screen can explain before the click


def test_archive_and_restore_round_trip(admin, world):
    _, client = admin
    pk = world["beta"].pk
    archived = post(client, f"{BASE}departments/{pk}/archive/", {"reason": "Merged"})
    assert archived.status_code == 200 and archived.json()["is_archived"] is True
    assert patch(client, f"{BASE}departments/{pk}/", {"name": "Edit"}).status_code == 400
    restored = post(client, f"{BASE}departments/{pk}/restore/")
    assert restored.status_code == 200 and restored.json()["is_archived"] is False


def test_set_and_clear_the_head(admin, make_user, world):
    _, client = admin
    person = make_user("headperson", full_name="Head Person")
    assignment = post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    )
    assert assignment.status_code == 201
    pk = world["alpha"].pk

    outsider = make_user("outsider")
    refused = put(client, f"{BASE}departments/{pk}/head/", {"user": str(outsider.pk)})
    assert refused.status_code == 400 and "hold a position" in error_text(refused)

    done = put(client, f"{BASE}departments/{pk}/head/", {"user": str(person.pk)})
    assert done.status_code == 200 and done.json()["head"]["full_name"] == "Head Person"
    cleared = put(client, f"{BASE}departments/{pk}/head/", {"user": None})
    assert cleared.json()["head"] is None


# --- Positions ---


def test_position_flow_and_filters(admin, world):
    _, client = admin
    made = post(
        client,
        BASE + "positions/",
        {
            "department": str(world["alpha"].pk),
            "title": "Supervisor",
            "reports_to": str(world["clerk_b"].pk),
        },
    )
    assert made.status_code == 201
    body = made.json()
    assert body["department"]["name"] == "Alpha" and body["reports_to"]["department"] == "Beta"
    renamed = patch(client, f"{BASE}positions/{body['id']}/", {"title": "Senior Supervisor"})
    assert renamed.json()["title"] == "Senior Supervisor" and renamed.json()["version"] == 2

    in_alpha = results(client.get(BASE + "positions/", {"department": str(world["alpha"].pk)}))
    assert {p["title"] for p in in_alpha} == {"Clerk", "Senior Supervisor"}
    assert {p["title"] for p in results(client.get(BASE + "positions/", {"q": "senior"}))} == {
        "Senior Supervisor"
    }


def test_position_cycles_and_archive_blocking_through_the_api(admin, make_user, world):
    _, client = admin
    actor = admin[0]
    boss = services.create_position(actor, department=world["alpha"], title="Boss")
    worker_position = services.create_position(
        actor, department=world["alpha"], title="Worker", reports_to=boss
    )
    loop = patch(client, f"{BASE}positions/{boss.pk}/", {"reports_to": str(worker_position.pk)})
    assert loop.status_code == 400 and "cannot report to itself" in error_text(loop)

    blocked = post(client, f"{BASE}positions/{boss.pk}/archive/")
    assert blocked.status_code == 400 and "report to it" in error_text(blocked)
    assert client.get(f"{BASE}positions/{boss.pk}/").json()["archive_blockers"]

    free = post(client, f"{BASE}positions/{worker_position.pk}/archive/")
    assert free.status_code == 200 and free.json()["is_archived"] is True
    assert post(client, f"{BASE}positions/{worker_position.pk}/restore/").status_code == 200


# --- Staff assignments and the link to scoped access ---


def test_assignment_flow(admin, make_user, world):
    _, client = admin
    person = make_user("worker", full_name="Worker One")
    made = post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    )
    assert made.status_code == 201
    row = made.json()
    assert row["is_primary"] is True and row["is_current"] is True
    assert row["department"]["name"] == "Alpha" and row["user"]["full_name"] == "Worker One"
    person.refresh_from_db()
    assert person.department_id == world["alpha"].pk

    again = post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    )
    assert again.status_code == 400

    listed = results(client.get(BASE + "assignments/", {"department": str(world["alpha"].pk)}))
    assert [a["id"] for a in listed] == [row["id"]]
    assert results(client.get(BASE + "assignments/", {"q": "worker one"}))[0]["id"] == row["id"]

    ended = post(client, f"{BASE}assignments/{row['id']}/end/")
    assert ended.status_code == 200 and ended.json()["is_current"] is False
    assert (
        results(client.get(BASE + "assignments/", {"user": str(person.pk)})) == []
    )  # current only
    past = results(client.get(BASE + "assignments/", {"user": str(person.pk), "current": "false"}))
    assert [a["id"] for a in past] == [row["id"]]
    person.refresh_from_db()
    assert person.department_id is None


def test_transfer_and_make_primary_through_the_api(admin, make_user, world):
    _, client = admin
    person = make_user("mover")
    first = post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    ).json()
    moved = post(
        client,
        f"{BASE}assignments/{first['id']}/transfer/",
        {"position": str(world["clerk_b"].pk)},
    )
    assert moved.status_code == 201 and moved.json()["department"]["name"] == "Beta"
    person.refresh_from_db()
    assert person.department_id == world["beta"].pk

    extra = post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    ).json()
    assert extra["is_primary"] is False
    swapped = post(client, f"{BASE}assignments/{extra['id']}/make-primary/")
    assert swapped.status_code == 200 and swapped.json()["is_primary"] is True
    person.refresh_from_db()
    assert person.department_id == world["alpha"].pk


def test_reporting_line_cycle_is_refused_through_the_api(admin, make_user, world):
    _, client = admin
    ann, bob = make_user("ann"), make_user("bob")
    a = post(
        client,
        BASE + "assignments/",
        {"user": str(ann.pk), "position": str(world["clerk_a"].pk), "reports_to_user": str(bob.pk)},
    ).json()
    b = post(
        client, BASE + "assignments/", {"user": str(bob.pk), "position": str(world["clerk_b"].pk)}
    ).json()
    loop = patch(client, f"{BASE}assignments/{b['id']}/", {"reports_to_user": str(ann.pk)})
    assert loop.status_code == 400 and "themselves" in error_text(loop)
    fine = patch(client, f"{BASE}assignments/{a['id']}/", {"reports_to_user": None})
    assert fine.status_code == 200 and fine.json()["reports_to_user"] is None


def test_people_search_returns_names_only(admin, make_user):
    _, client = admin
    make_user("searchable", full_name="Searchable Person", phone="+255 700 111 222")
    make_user("dormant", full_name="Dormant Person", status="INACTIVE")
    rows = results(client.get(BASE + "people/", {"q": "searchable"}))
    assert rows == [
        {
            "id": str(rows[0]["id"]),
            "full_name": "Searchable Person",
            "username": "searchable",
        }
    ]
    assert results(client.get(BASE + "people/", {"q": "dormant"})) == []  # inactive accounts hidden
    text = client.get(BASE + "people/").content.decode()
    assert "255 700" not in text and "@example.org" not in text and "password" not in text


def test_moving_a_person_changes_what_they_can_see(admin, make_user, new_client, departments):
    """The point of Slice 4: department scope now follows real staff assignments."""
    actor = admin[0]
    owner = make_user("record.owner")
    in_a = Record.objects.create(title="Held in A", department=departments["A"], created_by=owner)
    in_b = Record.objects.create(title="Held in B", department=departments["B"], created_by=owner)
    position_a = services.create_position(actor, department=departments["A"], title="Officer")
    position_b = services.create_position(actor, department=departments["B"], title="Officer")

    role = Role.objects.create(code="DEPTVIEW", name="Department viewer")
    RolePermission.objects.create(
        role=role,
        permission=Permission.objects.get(module="finance", action="VIEW"),
        scope="DEPARTMENT",
    )
    worker = make_user("worker")
    UserRole.objects.create(user=worker, role=role)  # a role that follows their department
    client = new_client()
    sign_in(client, "worker")
    records = "/api/v1/test/records/"

    def titles():
        response = client.get(records)
        if response.status_code == 403:  # no department means the scoped grant gives nothing
            return set()
        return {r["title"] for r in response.json()["results"]}

    assert client.get(records).status_code == 403  # no assignment, so no department yet

    first = services.assign_staff(actor, worker, position_a)
    assert titles() == {"Held in A"}
    assert client.get(f"{records}{in_b.pk}/").status_code == 404

    services.transfer_staff(actor, first, position_b)
    assert titles() == {"Held in B"}  # same session, no sign-in needed
    assert client.get(f"{records}{in_a.pk}/").status_code == 404

    current = StaffAssignment.objects.get(user=worker, end_date__isnull=True)
    services.end_assignment(actor, current)
    assert titles() == set()


def test_a_second_assignment_in_another_department_does_not_widen_access(
    admin, make_user, new_client, departments
):
    """Only the MAIN assignment sets the department scope."""
    actor = admin[0]
    owner = make_user("record.owner")
    Record.objects.create(title="Held in A", department=departments["A"], created_by=owner)
    Record.objects.create(title="Held in B", department=departments["B"], created_by=owner)
    position_a = services.create_position(actor, department=departments["A"], title="Officer")
    position_b = services.create_position(actor, department=departments["B"], title="Officer")
    role = Role.objects.create(code="DEPTVIEW", name="Department viewer")
    RolePermission.objects.create(
        role=role,
        permission=Permission.objects.get(module="finance", action="VIEW"),
        scope="DEPARTMENT",
    )
    worker = make_user("worker")
    UserRole.objects.create(user=worker, role=role)
    client = new_client()
    sign_in(client, "worker")
    services.assign_staff(actor, worker, position_a)
    services.assign_staff(actor, worker, position_b)  # additional
    titles = {r["title"] for r in client.get("/api/v1/test/records/").json()["results"]}
    assert titles == {"Held in A"}


# --- Approval chains ---


def test_chain_round_trip_through_the_api(admin, make_user, world):
    _, client = admin
    approver = make_user("approver")
    role = Role.objects.get(code="FINANCE_OFFICER")
    url = f"{BASE}departments/{world['alpha'].pk}/approval-chains/"
    assert client.get(url).json() == {"chains": {}}

    saved = put(
        client,
        url + "leave/",
        {
            "steps": [
                {"approver_type": "REPORTS_TO"},
                {"approver_type": "POSITION", "position": str(world["clerk_a"].pk)},
                {"approver_type": "ROLE", "role": str(role.pk)},
                {"approver_type": "USER", "user": str(approver.pk)},
                {"approver_type": "DEPARTMENT_HEAD"},
            ]
        },
    )
    assert saved.status_code == 200
    assert [s["step_order"] for s in saved.json()["steps"]] == [1, 2, 3, 4, 5]
    chains = client.get(url).json()["chains"]
    assert list(chains) == ["LEAVE"]
    assert [s["label"] for s in chains["LEAVE"]][1:4] == [
        "Position: Clerk",
        "Role: Finance Officer",
        "Person: approver",
    ]

    cleared = put(client, url + "LEAVE/", {"steps": []})
    assert cleared.status_code == 200 and client.get(url).json() == {"chains": {}}


def test_bad_chains_are_refused_and_change_nothing(admin, world):
    _, client = admin
    url = f"{BASE}departments/{world['alpha'].pk}/approval-chains/DEFAULT/"
    put(client, url, {"steps": [{"approver_type": "DEPARTMENT_HEAD"}]})
    for steps in (
        [{"approver_type": "BOSS"}],
        [{"approver_type": "POSITION"}],
        [{"approver_type": "ROLE", "role": "not-a-uuid"}],
        [{"approver_type": "REPORTS_TO"}] * 7,
        [{"approver_type": "DEPARTMENT_HEAD"}] * 2,
    ):
        assert put(client, url, {"steps": steps}).status_code == 400, steps
    assert put(client, url, {}).status_code == 400
    chains = client.get(f"{BASE}departments/{world['alpha'].pk}/approval-chains/").json()["chains"]
    assert [s["approver_type"] for s in chains["DEFAULT"]] == ["DEPARTMENT_HEAD"]


def test_options_list_roles_types_and_limits(admin):
    _, client = admin
    body = client.get(BASE + "options/").json()
    assert {r["name"] for r in body["roles"]} >= {"Finance Officer", "Administrator"}
    assert {t["value"] for t in body["approver_types"]} == {
        "POSITION",
        "ROLE",
        "DEPARTMENT_HEAD",
        "REPORTS_TO",
        "USER",
    }
    assert body["max_chain_steps"] == 6 and body["default_request_type"] == "DEFAULT"


# --- Tree ---


def test_tree_endpoint_returns_the_nested_structure(admin, make_user, world):
    _, client = admin
    services.update_department(admin[0], world["beta"], parent=world["alpha"])
    services.assign_staff(admin[0], make_user("worker", full_name="Worker One"), world["clerk_a"])
    roots = client.get(BASE + "tree/").json()["results"]
    alpha = next(node for node in roots if node["code"] == "ALPHA")
    assert [c["code"] for c in alpha["children"]] == ["BETA"] and alpha["staff_count"] == 1
    assert "ADMINISTRATION" in {node["code"] for node in roots}
    everything = client.get(BASE + "tree/", {"include_archived": "true"}).json()["results"]
    assert len(everything) >= len(roots)


# --- Audit ---


def test_changes_made_through_the_api_appear_in_the_audit_log(admin, make_user, world):
    _, client = admin
    post(client, BASE + "departments/", {"code": "AUDITED", "name": "Audited"})
    person = make_user("worker")
    post(
        client,
        BASE + "assignments/",
        {"user": str(person.pk), "position": str(world["clerk_a"].pk)},
    )
    post(client, f"{BASE}departments/{world['beta'].pk}/archive/", {"reason": "Closed"})

    pairs = set(AuditEvent.objects.values_list("event_type", "object_type"))
    assert ("RECORD_CREATED", "organisation.Department") in pairs
    assert ("RECORD_CREATED", "organisation.StaffAssignment") in pairs
    assert ("RECORD_ARCHIVED", "organisation.Department") in pairs
    assert ("USER_UPDATED", "accounts.User") in pairs
    event = AuditEvent.objects.get(event_type="RECORD_ARCHIVED")
    assert event.actor_username == "org.boss" and event.request_id and event.metadata["reason"]


def test_a_refused_change_leaves_no_audit_event_and_no_change(admin, make_user, world):
    _, client = admin
    services.assign_staff(admin[0], make_user("worker"), world["clerk_a"])
    before = AuditEvent.objects.count()
    response = post(client, f"{BASE}departments/{world['alpha'].pk}/archive/")
    assert response.status_code == 400
    assert AuditEvent.objects.count() == before
    world["alpha"].refresh_from_db()
    assert world["alpha"].is_archived is False


def test_a_department_scoped_audit_viewer_sees_only_their_departments_changes(
    admin, make_user, new_client, world
):
    """Organisation events carry the department, so audit scope works for them (Slice 3)."""
    actor = admin[0]
    services.update_department(actor, world["alpha"], description="Changed in Alpha")
    services.update_department(actor, world["beta"], description="Changed in Beta")
    role = make_role(("audit", "VIEW", "DEPARTMENT"))
    viewer = make_user("auditor")
    UserRole.objects.create(user=viewer, role=role, department=world["alpha"])
    client = APIClient(enforce_csrf_checks=True)
    sign_in(client, "auditor")

    rows = client.get("/api/v1/audit/events/", {"event_type": "RECORD_UPDATED"}).json()["results"]

    assert {r["object_id"] for r in rows} == {str(world["alpha"].pk)}


def test_no_email_phone_or_password_in_any_organisation_response(admin, make_user, world):
    _, client = admin
    person = make_user("worker", phone="+255 700 999 888")
    services.assign_staff(admin[0], person, world["clerk_a"])
    blob = ""
    for url in ("tree/", "departments/", "positions/", "assignments/", "people/"):
        blob += client.get(BASE + url).content.decode()
    assert "255 700 999" not in blob and "@example.org" not in blob
    assert "password" not in blob.lower() and "pbkdf2" not in blob and "md5" not in blob
    assert Position.objects.count() > 0

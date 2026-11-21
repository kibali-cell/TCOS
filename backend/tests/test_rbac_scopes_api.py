"""Scoped access through real API calls: departments, own, assigned, record grants, roles."""

import itertools
from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient

from apps.rbac.models import Permission, RecordGrant, Role, RolePermission, UserRole

from .conftest import delete, patch, post, sign_in
from .rbac_testapp.models import Record

RECORDS = "/api/v1/test/records/"
_n = itertools.count(1)


@pytest.fixture
def world(make_user, departments):
    """Records in both departments plus a few owned or assigned to specific people."""
    owner = make_user("record.owner")
    return {
        "a1": Record.objects.create(title="A one", department=departments["A"], created_by=owner),
        "a2": Record.objects.create(title="A two", department=departments["A"], created_by=owner),
        "b1": Record.objects.create(title="B one", department=departments["B"], created_by=owner),
        "b2": Record.objects.create(title="B two", department=departments["B"], created_by=owner),
        "none": Record.objects.create(title="No dept", created_by=owner),
    }


def officer(username, grants, *, department=None, make=None, **assignment):
    """Create a user holding a one-off role with these (action, scope) pairs on finance."""
    role = Role.objects.create(code=f"S{next(_n)}", name=f"Scope role {next(_n)}")
    for action, scope in grants:
        RolePermission.objects.create(
            role=role,
            permission=Permission.objects.get(module="finance", action=action),
            scope=scope,
        )
    user = make(username, department=department)
    UserRole.objects.create(user=user, role=role, **assignment)
    client = APIClient(enforce_csrf_checks=True)
    assert sign_in(client, username).status_code == 200
    return user, client


def titles(client):
    body = client.get(RECORDS).json()
    return {row["title"] for row in body["results"]}, body["count"]


# --- Department scope ------------------------------------------------------------------


def test_department_a_user_cannot_see_department_b_records(make_user, departments, world):
    _u, client = officer(
        "dept.a.user", [("VIEW", "DEPARTMENT")], department=departments["A"], make=make_user
    )
    seen, count = titles(client)
    assert seen == {"A one", "A two"} and count == 2  # the count does not leak B's records either


def test_department_b_user_sees_the_mirror_image(make_user, departments, world):
    _u, client = officer(
        "dept.b.user", [("VIEW", "DEPARTMENT")], department=departments["B"], make=make_user
    )
    assert titles(client)[0] == {"B one", "B two"}


def test_out_of_department_records_are_404_not_403(make_user, departments, world):
    """A record outside your scope looks exactly like a record that does not exist."""
    _u, client = officer(
        "dept.a.user",
        [("VIEW", "DEPARTMENT"), ("EDIT", "DEPARTMENT"), ("DELETE", "DEPARTMENT")],
        department=departments["A"],
        make=make_user,
    )
    secret = f"{RECORDS}{world['b1'].pk}/"
    missing = f"{RECORDS}6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11/"
    assert client.get(secret).status_code == 404
    assert client.get(missing).status_code == 404
    assert client.get(secret).content == client.get(missing).content
    assert patch(client, secret, {"title": "hacked"}).status_code == 404
    assert delete(client, secret).status_code == 404
    world["b1"].refresh_from_db()
    assert world["b1"].title == "B one"


def test_in_department_records_can_be_edited_and_deleted(make_user, departments, world):
    _u, client = officer(
        "dept.a.user",
        [("VIEW", "DEPARTMENT"), ("EDIT", "DEPARTMENT"), ("DELETE", "DEPARTMENT")],
        department=departments["A"],
        make=make_user,
    )
    assert patch(client, f"{RECORDS}{world['a1'].pk}/", {"title": "Edited"}).status_code == 200
    assert delete(client, f"{RECORDS}{world['a2'].pk}/").status_code == 204


def test_cannot_move_a_record_into_another_department_by_editing(make_user, departments, world):
    """Writes are re-checked against the record's new state, so it cannot leave your scope."""
    _u, client = officer(
        "dept.a.user",
        [("VIEW", "DEPARTMENT"), ("EDIT", "DEPARTMENT")],
        department=departments["A"],
        make=make_user,
    )
    url = f"{RECORDS}{world['a1'].pk}/"
    response = patch(client, url, {"department": str(departments["B"].pk)})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "outside_scope"
    world["a1"].refresh_from_db()
    assert world["a1"].department_id == departments["A"].pk  # unchanged
    assert patch(client, url, {"title": "Fine"}).status_code == 200  # ordinary edits still work


def test_creating_is_limited_to_the_users_own_department(make_user, departments):
    _u, client = officer(
        "dept.a.user", [("CREATE", "DEPARTMENT")], department=departments["A"], make=make_user
    )
    ok = post(client, RECORDS, {"title": "Mine", "department": str(departments["A"].pk)})
    elsewhere = post(client, RECORDS, {"title": "Theirs", "department": str(departments["B"].pk)})
    nowhere = post(client, RECORDS, {"title": "Floating"})
    assert (ok.status_code, elsewhere.status_code, nowhere.status_code) == (201, 403, 403)
    assert set(Record.objects.values_list("title", flat=True)) == {"Mine"}


def test_a_department_user_without_a_department_sees_nothing(make_user, world):
    _u, client = officer("drifter.user", [("VIEW", "DEPARTMENT")], make=make_user)
    assert client.get(RECORDS).status_code == 403  # an empty grant is no grant
    assert client.get("/api/v1/auth/me/").json()["permissions"] == {}


# --- Own and assigned ------------------------------------------------------------------


def test_own_scope_sees_only_what_the_user_created(make_user, departments, world):
    user, client = officer("own.user", [("VIEW", "OWN"), ("CREATE", "OWN")], make=make_user)
    assert titles(client)[1] == 0
    created = post(client, RECORDS, {"title": "Mine", "department": str(departments["B"].pk)})
    assert created.status_code == 201
    assert titles(client)[0] == {"Mine"}
    assert Record.objects.get(title="Mine").created_by_id == user.pk  # the server sets the owner


def test_the_client_cannot_choose_who_owns_a_record(make_user, world):
    user, client = officer("own.user", [("VIEW", "OWN"), ("CREATE", "OWN")], make=make_user)
    victim = world["a1"].created_by
    response = post(client, RECORDS, {"title": "Spoofed", "created_by": str(victim.pk)})
    assert response.status_code == 201
    assert Record.objects.get(title="Spoofed").created_by_id == user.pk


def test_assigned_scope_sees_assigned_records(make_user, world):
    user, client = officer("assigned.user", [("VIEW", "ASSIGNED")], make=make_user)
    Record.objects.filter(pk=world["b2"].pk).update(assigned_to=user)
    assert titles(client)[0] == {"B two"}


# --- Several roles through the API -----------------------------------------------------------


def test_department_restricted_role_plus_unrestricted_role(make_user, departments, world):
    """VIEW everywhere from one role; EDIT only inside Department B from another."""
    user, client = officer(
        "two.roles", [("VIEW", "ALL")], department=departments["A"], make=make_user
    )
    edit_role = Role.objects.create(code="EDITB", name="Edit in B")
    RolePermission.objects.create(
        role=edit_role,
        permission=Permission.objects.get(module="finance", action="EDIT"),
        scope="ALL",
    )
    UserRole.objects.create(user=user, role=edit_role, department=departments["B"])

    assert titles(client)[1] == 5  # sees everything
    assert patch(client, f"{RECORDS}{world['b1'].pk}/", {"title": "Edited in B"}).status_code == 200
    # outside Department B the edit permission does not exist for this person: 404, not 403
    assert patch(client, f"{RECORDS}{world['a1'].pk}/", {"title": "nope"}).status_code == 404
    world["a1"].refresh_from_db()
    assert world["a1"].title == "A one"


def test_an_expired_role_stops_working_mid_session(make_user, world):
    user, client = officer(
        "temp.user",
        [("VIEW", "ALL")],
        make=make_user,
        valid_to=timezone.localdate() + timedelta(days=1),
    )
    assert client.get(RECORDS).status_code == 200
    UserRole.objects.filter(user=user).update(valid_to=timezone.localdate() - timedelta(days=1))
    assert client.get(RECORDS).status_code == 403


def test_removing_one_role_leaves_the_other_working(make_user, world):
    user, client = officer("two.hats", [("VIEW", "ALL")], make=make_user)
    other = Role.objects.get(code="STOREKEEPER")
    extra = UserRole.objects.create(user=user, role=other)
    perms = client.get("/api/v1/auth/me/").json()["permissions"]
    assert "stores" in perms and "finance" in perms

    extra.revoked_at = timezone.now()
    extra.save()
    perms = client.get("/api/v1/auth/me/").json()["permissions"]
    assert "stores" not in perms and "finance" in perms
    assert client.get(RECORDS).status_code == 200


# --- Record grants ----------------------------------------------------------------------------


def test_record_grant_opens_one_record_outside_the_users_scope(make_user, departments, world):
    user, client = officer(
        "granted.user",
        [("VIEW", "DEPARTMENT"), ("EDIT", "DEPARTMENT")],
        department=departments["A"],
        make=make_user,
    )
    assert client.get(f"{RECORDS}{world['b1'].pk}/").status_code == 404

    RecordGrant.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(Record),
        object_id=world["b1"].pk,
        action="VIEW",
    )
    assert client.get(f"{RECORDS}{world['b1'].pk}/").status_code == 200
    assert client.get(f"{RECORDS}{world['b2'].pk}/").status_code == 404  # only that record
    assert (
        patch(client, f"{RECORDS}{world['b1'].pk}/", {"title": "x"}).status_code == 404
    )  # only that action
    assert titles(client)[0] == {"A one", "A two", "B one"}


def test_revoking_a_record_grant_takes_effect_at_once(make_user, departments, world):
    user, client = officer("granted.user", [("VIEW", "OWN")], make=make_user)
    grant = RecordGrant.objects.create(
        user=user,
        content_type=ContentType.objects.get_for_model(Record),
        object_id=world["b1"].pk,
        action="VIEW",
    )
    assert client.get(f"{RECORDS}{world['b1'].pk}/").status_code == 200
    grant.revoked_at = timezone.now()
    grant.save()
    assert client.get(f"{RECORDS}{world['b1'].pk}/").status_code == 404

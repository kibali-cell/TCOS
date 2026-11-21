"""Managing roles and assignments: protections, escalation and live effect on the API."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.rbac.models import Permission, Role, RolePermission, UserRole

from .conftest import delete, give_role, patch, post, put, sign_in
from .rbac_testapp.models import Record

ROLES = "/api/v1/rbac/roles/"
RECORDS = "/api/v1/test/records/"
_n = itertools.count(1)


def user_roles_url(user):
    return f"/api/v1/rbac/users/{user.pk}/roles/"


def grants_url(role):
    return f"{ROLES}{role.pk}/grants/"


def cell(module, action, scope="ALL"):
    return {"module": module, "action": action, "scope": scope}


def make_role(*cells):
    role = Role.objects.create(code=f"T{next(_n)}", name=f"Role {next(_n)}")
    for module, action, scope in cells:
        RolePermission.objects.create(
            role=role, permission=Permission.objects.get(module=module, action=action), scope=scope
        )
    return role


def client_for(username):
    """A browser signed in as an existing user (CSRF enforced like a real browser)."""
    client = APIClient(enforce_csrf_checks=True)
    assert sign_in(client, username).status_code == 200
    return client


def manager_role():
    return make_role(("users", "MANAGE_USERS", "ALL"), ("users", "VIEW", "ALL"))


@pytest.fixture
def admin(staff):
    return staff("ADMINISTRATOR", username="admin.one")


# --- Roles: create, edit, delete ---------------------------------------------------------


def test_create_a_role_with_grants(admin):
    _user, client = admin
    response = post(
        client,
        ROLES,
        {
            "name": "Field Visitor",
            "description": "Visits families",
            "grants": [cell("social_welfare", "VIEW", "ASSIGNED")],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "FIELD_VISITOR" and not body["is_system"]
    assert body["grants"] == [cell("social_welfare", "VIEW", "ASSIGNED")]


def test_role_codes_stay_unique(admin):
    _user, client = admin
    post(client, ROLES, {"name": "Field Visitor"})
    second = post(client, ROLES, {"name": "Field-Visitor!"})
    assert second.status_code == 201
    assert second.json()["code"] == "FIELD_VISITOR_2"


def test_duplicate_role_names_are_refused_ignoring_case(admin):
    _user, client = admin
    assert post(client, ROLES, {"name": "storekeeper"}).status_code == 400
    assert post(client, ROLES, {"name": "  "}).status_code == 400


def test_edit_name_and_description_of_a_role(admin):
    _user, client = admin
    role = Role.objects.get(code="STOREKEEPER")
    response = patch(client, f"{ROLES}{role.pk}/", {"name": "Store Manager", "description": "x"})
    assert response.status_code == 200 and response.json()["name"] == "Store Manager"
    assert response.json()["code"] == "STOREKEEPER"  # the code never changes


def test_seeded_roles_cannot_be_deleted(admin):
    _user, client = admin
    role = Role.objects.get(code="STOREKEEPER")
    assert delete(client, f"{ROLES}{role.pk}/").status_code == 400
    assert Role.objects.filter(pk=role.pk).exists()


def test_unused_custom_role_can_be_deleted(admin):
    _user, client = admin
    role = make_role(("stores", "VIEW", "ALL"))
    assert delete(client, f"{ROLES}{role.pk}/").status_code == 204
    assert not Role.objects.filter(pk=role.pk).exists()


def test_a_role_that_was_ever_assigned_cannot_be_deleted(admin, make_user):
    _user, client = admin
    role = make_role(("stores", "VIEW", "ALL"))
    holder = make_user("holder.one")
    post(client, user_roles_url(holder), {"role": str(role.pk)})
    response = delete(client, f"{ROLES}{role.pk}/")
    assert response.status_code == 400 and "Deactivate" in response.json()["error"][
        "message"
    ] + str(response.json()["error"]["details"])


def test_unknown_role_is_404(admin):
    _user, client = admin
    assert client.get(f"{ROLES}6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11/").status_code == 404


# --- The permission matrix ------------------------------------------------------------------


def test_matrix_replace_validates_every_row(admin):
    _user, client = admin
    role = make_role()
    bad = put(
        client,
        grants_url(role),
        {
            "grants": [
                cell("nowhere", "VIEW"),
                cell("finance", "TELEPORT"),
                cell("finance", "VIEW", "EVERYONE"),
                cell("stores", "VIEW"),
                cell("stores", "VIEW"),
            ]
        },
    )
    assert bad.status_code == 400
    assert len(bad.json()["error"]["details"]["grants"]) == 4
    assert role.grants.count() == 0  # nothing was applied


def test_matrix_replace_is_atomic_and_each_cell_is_independent(admin):
    _user, client = admin
    role = make_role(("stores", "VIEW", "ALL"), ("stores", "EDIT", "OWN"))
    response = put(
        client,
        grants_url(role),
        {"grants": [cell("stores", "EDIT", "DEPARTMENT"), cell("projects", "VIEW", "ASSIGNED")]},
    )
    assert response.status_code == 200
    stored = {(g["module"], g["action"]): g["scope"] for g in response.json()["grants"]}
    assert stored == {("stores", "EDIT"): "DEPARTMENT", ("projects", "VIEW"): "ASSIGNED"}


def test_an_empty_matrix_removes_every_grant(admin):
    _user, client = admin
    role = make_role(("stores", "VIEW", "ALL"))
    assert put(client, grants_url(role), {"grants": []}).status_code == 200
    assert role.grants.count() == 0


def test_acceptance_changing_a_role_changes_api_behaviour_immediately(admin, new_client, make_user):
    """The slice's acceptance test: edit the matrix, the very next request behaves differently."""
    _admin, admin_client = admin
    record = Record.objects.create(title="Ledger", created_by=make_user("ledger.owner"))
    role = make_role()
    clerk = make_user("clerk.user")
    give_role_obj = UserRole.objects.create(user=clerk, role=role)
    assert give_role_obj.pk
    clerk_client = new_client()
    assert sign_in(clerk_client, "clerk.user").status_code == 200  # stays signed in throughout

    assert clerk_client.get(RECORDS).status_code == 403  # no permission yet

    put(admin_client, grants_url(role), {"grants": [cell("finance", "VIEW")]})
    assert clerk_client.get(RECORDS).status_code == 200
    assert patch(clerk_client, f"{RECORDS}{record.pk}/", {"title": "x"}).status_code == 403

    put(
        admin_client,
        grants_url(role),
        {"grants": [cell("finance", "VIEW"), cell("finance", "EDIT")]},
    )
    assert patch(clerk_client, f"{RECORDS}{record.pk}/", {"title": "Edited"}).status_code == 200

    put(admin_client, grants_url(role), {"grants": []})
    assert clerk_client.get(RECORDS).status_code == 403  # and gone again
    me = clerk_client.get("/api/v1/auth/me/").json()
    assert me["permissions"] == {}


def test_deactivating_a_role_cuts_access_at_once(admin, new_client, make_user):
    _admin, admin_client = admin
    role = make_role(("finance", "VIEW", "ALL"))
    user = make_user("someone.else")
    UserRole.objects.create(user=user, role=role)
    client = new_client()
    sign_in(client, "someone.else")
    assert client.get(RECORDS).status_code == 200

    assert patch(admin_client, f"{ROLES}{role.pk}/", {"is_active": False}).status_code == 200
    assert client.get(RECORDS).status_code == 403

    patch(admin_client, f"{ROLES}{role.pk}/", {"is_active": True})
    assert client.get(RECORDS).status_code == 200


# --- Assignments --------------------------------------------------------------------------


def test_assign_with_department_and_dates_then_revoke(admin, make_user, departments):
    _admin, client = admin
    person = make_user("new.officer")
    role = Role.objects.get(code="FINANCE_OFFICER")
    today = timezone.localdate()

    response = post(
        client,
        user_roles_url(person),
        {
            "role": str(role.pk),
            "department": str(departments["A"].pk),
            "valid_from": str(today),
            "valid_to": str(today + timedelta(days=30)),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert (
        body["department"]["name"] == "Department A" and body["role"]["code"] == "FINANCE_OFFICER"
    )

    listing = client.get(user_roles_url(person)).json()["results"]
    assert len(listing) == 1

    assert delete(client, f"{user_roles_url(person)}{body['id']}/").status_code == 204
    assert client.get(user_roles_url(person)).json()["results"] == []
    kept = UserRole.objects.get(pk=body["id"])
    assert kept.revoked_at is not None and kept.revoked_by is not None  # history is kept


def test_assignment_rules(admin, make_user, departments):
    _admin, client = admin
    person = make_user("target.person")
    role = Role.objects.get(code="STOREKEEPER")
    url = user_roles_url(person)

    assert post(client, url, {"role": str(role.pk)}).status_code == 201
    assert post(client, url, {"role": str(role.pk)}).status_code == 400  # already holds it
    same_dept = {"role": str(role.pk), "department": str(departments["A"].pk)}
    assert post(client, url, same_dept).status_code == 201  # but a department-limited copy is fine
    assert post(client, url, same_dept).status_code == 400

    reversed_dates = {"role": str(role.pk), "valid_from": "2026-12-31", "valid_to": "2026-01-01"}
    assert post(client, url, reversed_dates).status_code == 400

    Role.objects.filter(pk=role.pk).update(is_active=False)
    inactive_role = post(
        client, url, {"role": str(role.pk), "department": str(departments["B"].pk)}
    )
    assert inactive_role.status_code == 400

    departments["B"].is_active = False
    departments["B"].save()
    other = Role.objects.get(code="HR_OFFICER")
    assert (
        post(
            client, url, {"role": str(other.pk), "department": str(departments["B"].pk)}
        ).status_code
        == 400
    )
    assert post(client, url, {"role": "not-a-uuid"}).status_code == 400
    assert (
        client.get("/api/v1/rbac/users/6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11/roles/").status_code
        == 404
    )


def test_a_revoked_assignment_can_be_granted_again(admin, make_user):
    _admin, client = admin
    person = make_user("again.person")
    role = Role.objects.get(code="STOREKEEPER")
    first = post(client, user_roles_url(person), {"role": str(role.pk)}).json()
    delete(client, f"{user_roles_url(person)}{first['id']}/")
    assert post(client, user_roles_url(person), {"role": str(role.pk)}).status_code == 201
    assert UserRole.objects.filter(user=person, role=role).count() == 2


def test_assigning_a_role_changes_what_the_person_can_do_at_once(admin, new_client, make_user):
    _admin, admin_client = admin
    person = make_user("fresh.hire")
    client = new_client()
    sign_in(client, "fresh.hire")
    assert client.get(RECORDS).status_code == 403

    finance = Role.objects.get(code="FINANCE_OFFICER")
    assignment = post(admin_client, user_roles_url(person), {"role": str(finance.pk)}).json()
    assert client.get(RECORDS).status_code == 200

    delete(admin_client, f"{user_roles_url(person)}{assignment['id']}/")
    assert client.get(RECORDS).status_code == 403


def test_a_person_with_two_roles_through_the_api_has_both(admin, new_client, make_user):
    _admin, admin_client = admin
    person = make_user("two.hats")
    for code in ("FINANCE_OFFICER", "STOREKEEPER"):
        role = Role.objects.get(code=code)
        assert post(admin_client, user_roles_url(person), {"role": str(role.pk)}).status_code == 201
    client = new_client()
    sign_in(client, "two.hats")
    permissions = client.get("/api/v1/auth/me/").json()["permissions"]
    assert "finance" in permissions and "stores" in permissions and "medical" not in permissions
    assert {r["code"] for r in client.get("/api/v1/auth/me/").json()["roles"]} == {
        "FINANCE_OFFICER",
        "STOREKEEPER",
    }


# --- Escalation and lock-out protections ------------------------------------------------------


def test_nobody_can_give_themselves_a_role(admin, staff):
    """An administrator cannot grant themselves access they lack, even through the API."""
    user, client = admin
    medical = Role.objects.get(code="MEDICAL_OFFICER")
    response = post(client, user_roles_url(user), {"role": str(medical.pk)})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_escalation"
    assert not UserRole.objects.filter(user=user, role=medical).exists()
    assert "medical" not in client.get("/api/v1/auth/me/").json()["permissions"]


def test_nobody_can_edit_the_permissions_of_a_role_they_hold(admin):
    user, client = admin
    admin_role = Role.objects.get(code="ADMINISTRATOR")
    escalate = [cell("users", "MANAGE_USERS"), cell("medical", "VIEW")]
    response = put(client, grants_url(admin_role), {"grants": escalate})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_escalation"
    assert not RolePermission.objects.filter(role=admin_role, permission__module="medical").exists()


def test_nobody_can_edit_or_delete_or_deactivate_a_role_they_hold(make_user):
    actor = make_user("custom.admin")
    role = manager_role()
    UserRole.objects.create(user=actor, role=role)
    client = client_for("custom.admin")

    assert patch(client, f"{ROLES}{role.pk}/", {"name": "Mine now"}).status_code == 403
    assert delete(client, f"{ROLES}{role.pk}/").status_code == 403
    assert put(client, grants_url(role), {"grants": [cell("medical", "VIEW")]}).status_code == 403


def test_cannot_remove_your_own_roles(admin):
    user, client = admin
    mine = UserRole.objects.get(user=user)
    response = delete(client, f"{user_roles_url(user)}{mine.pk}/")
    assert response.status_code == 403
    assert UserRole.objects.get(pk=mine.pk).revoked_at is None


def test_a_user_without_manage_users_cannot_change_anything(staff, make_user):
    """Executive Director and HR Officer may look at roles but never change them."""
    target = make_user("target.user")
    for code in ("EXECUTIVE_DIRECTOR", "HR_OFFICER"):
        user, client = staff(code, username=f"{code.lower()}.x".replace("_", "."))
        role = Role.objects.get(code=code)
        storekeeper = Role.objects.get(code="STOREKEEPER")
        assert client.get(ROLES).status_code == 200  # may read
        assert patch(client, f"{ROLES}{storekeeper.pk}/", {"name": "x"}).status_code == 403
        assert (
            put(client, grants_url(role), {"grants": [cell("medical", "VIEW")]}).status_code == 403
        )
        assert post(client, user_roles_url(user), {"role": str(storekeeper.pk)}).status_code == 403
        assert (
            post(client, user_roles_url(target), {"role": str(storekeeper.pk)}).status_code == 403
        )
    assert not UserRole.objects.filter(user=target).exists()


def test_the_administrator_role_must_keep_manage_users(make_user):
    """Stops the system locking itself out. Done by a user who does not hold the role."""
    UserRole.objects.create(user=make_user("role.manager"), role=manager_role())
    client = client_for("role.manager")

    admin_role = Role.objects.get(code="ADMINISTRATOR")
    response = put(client, grants_url(admin_role), {"grants": [cell("audit", "VIEW")]})
    assert response.status_code == 400
    assert "Manage Users" in str(response.json())
    assert patch(client, f"{ROLES}{admin_role.pk}/", {"is_active": False}).status_code == 400
    assert delete(client, f"{ROLES}{admin_role.pk}/").status_code == 400


def test_the_last_working_administrator_cannot_be_removed(make_user):
    # Admin A is the only administrator whose account works; B's account is inactive.
    admin_a = make_user("admin.alpha")
    admin_b = make_user("admin.bravo", status="INACTIVE")
    a_role = give_role(admin_a, "ADMINISTRATOR")
    give_role(admin_b, "ADMINISTRATOR")

    UserRole.objects.create(user=make_user("helper.user"), role=manager_role())
    client = client_for("helper.user")

    response = delete(client, f"{user_roles_url(admin_a)}{a_role.pk}/")
    assert response.status_code == 400
    assert "last working Administrator" in str(response.json())
    assert UserRole.objects.get(pk=a_role.pk).revoked_at is None


def test_an_administrator_can_be_removed_when_another_works(make_user):
    admin_a = make_user("admin.alpha")
    admin_b = make_user("admin.bravo")
    a_role = give_role(admin_a, "ADMINISTRATOR")
    give_role(admin_b, "ADMINISTRATOR")
    client = client_for("admin.bravo")
    assert delete(client, f"{user_roles_url(admin_a)}{a_role.pk}/").status_code == 204


def test_expired_administrator_does_not_count_as_a_working_administrator(make_user):
    """An expired or restricted Administrator assignment cannot be relied on to keep control."""
    admin_a = make_user("admin.alpha")
    admin_b = make_user("admin.bravo")
    a_role = give_role(admin_a, "ADMINISTRATOR")
    give_role(admin_b, "ADMINISTRATOR", valid_to=timezone.localdate() - timedelta(days=1))
    UserRole.objects.create(user=make_user("helper.user"), role=manager_role())
    client = client_for("helper.user")
    assert delete(client, f"{user_roles_url(admin_a)}{a_role.pk}/").status_code == 400

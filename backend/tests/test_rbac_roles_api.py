"""Each of the 11 roles signs in and tries allowed and forbidden things over the real API."""

import pytest

from apps.rbac.models import Role

from .conftest import delete, patch, post
from .rbac_testapp.models import Record
from .test_rbac_seed import ROLE_CODES, expected_cells

LIST = "/api/v1/rbac/roles/"
RECORDS = "/api/v1/test/records/"  # a stand-in finance record endpoint using the real engine


def allowed(code, module, action):
    return (module, action) in expected_cells(code)


@pytest.fixture
def a_record(db, make_user, departments):
    return Record.objects.create(
        title="Budget line", department=departments["A"], created_by=make_user("record.owner")
    )


@pytest.mark.parametrize("code", ROLE_CODES)
def test_me_reports_exactly_the_roles_permissions(staff, departments, code):
    _user, client = staff(code, department=departments["A"])
    body = client.get("/api/v1/auth/me/").json()

    expected = {}
    for (module, action), scope in expected_cells(code).items():
        expected.setdefault(module, {})[action] = scope
    assert body["permissions"] == expected
    assert [r["code"] for r in body["roles"]] == [code]


@pytest.mark.parametrize("code", ROLE_CODES)
def test_role_screens_follow_users_permissions(staff, code):
    _user, client = staff(code)

    assert client.get(LIST).status_code == (200 if allowed(code, "users", "VIEW") else 403)
    assert client.get("/api/v1/rbac/catalogue/").status_code == (
        200 if allowed(code, "users", "VIEW") else 403
    )
    created = post(client, LIST, {"name": f"Made by {code}", "grants": []})
    assert created.status_code == (201 if allowed(code, "users", "MANAGE_USERS") else 403)


@pytest.mark.parametrize("code", ROLE_CODES)
def test_finance_records_follow_finance_permissions(staff, departments, a_record, code):
    _user, client = staff(code, department=departments["A"])
    url = f"{RECORDS}{a_record.pk}/"

    assert client.get(RECORDS).status_code == (200 if allowed(code, "finance", "VIEW") else 403)
    assert client.get(url).status_code == (200 if allowed(code, "finance", "VIEW") else 403)
    assert post(client, RECORDS, {"title": "New"}).status_code == (
        201 if allowed(code, "finance", "CREATE") else 403
    )
    assert patch(client, url, {"title": "Changed"}).status_code == (
        200 if allowed(code, "finance", "EDIT") else 403
    )
    assert delete(client, url).status_code == (204 if allowed(code, "finance", "DELETE") else 403)


@pytest.mark.parametrize("code", [c for c in ROLE_CODES if not allowed(c, "finance", "VIEW")])
def test_forbidden_responses_reveal_nothing(staff, a_record, code):
    """A refused request returns the standard error body and none of the record data."""
    _user, client = staff(code)
    response = client.get(f"{RECORDS}{a_record.pk}/")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert "Budget line" not in response.content.decode()


def test_ui_hidden_is_not_secure_a_user_without_access_calls_the_api_directly(staff, a_record):
    """The Medical Officer has no finance menu, but typing the URL must not work either."""
    _user, client = staff("MEDICAL_OFFICER")
    me = client.get("/api/v1/auth/me/").json()
    assert "finance" not in me["permissions"]  # the screen would hide it...
    assert client.get(RECORDS).status_code == 403  # ...and the server refuses anyway
    assert post(client, RECORDS, {"title": "sneaky"}).status_code == 403
    assert not Record.objects.filter(title="sneaky").exists()


def test_anonymous_callers_get_401_on_every_rbac_endpoint(new_client, a_record):
    anonymous = new_client()
    for url in (LIST, "/api/v1/rbac/catalogue/", "/api/v1/rbac/departments/", RECORDS):
        assert anonymous.get(url).status_code == 401, url


def test_users_must_change_password_before_any_module_access(staff, a_record):
    _user, client = staff("FINANCE_OFFICER", must_change_password=True)
    assert client.get(RECORDS).status_code == 403
    assert client.get("/api/v1/auth/me/").status_code == 200  # but may reach their account


def test_the_catalogue_lists_every_module_action_and_scope(staff):
    _user, client = staff("ADMINISTRATOR")
    body = client.get("/api/v1/rbac/catalogue/").json()
    assert len(body["modules"]) == 15 and len(body["actions"]) == 8
    assert body["scopes"] == ["ALL", "DEPARTMENT", "OWN", "ASSIGNED"]


def test_all_eleven_seeded_roles_are_listed_with_holder_counts(staff):
    _admin, client = staff("ADMINISTRATOR")
    rows = client.get(LIST).json()["results"]
    assert {r["code"] for r in rows} == set(ROLE_CODES)
    assert next(r for r in rows if r["code"] == "ADMINISTRATOR")["holders"] == 1
    assert all(r["is_system"] for r in rows)
    assert Role.objects.count() == 11

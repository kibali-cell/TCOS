"""User management API: permissions, protections and what changes."""

import pytest

from apps.accounts.models import User, UserSession
from apps.audit import events
from apps.audit.models import AuditEvent
from tests.conftest import delete, give_role, patch, post, sign_in  # noqa: F401

URL = "/api/v1/users/"


def uurl(user, *tail):
    return f"{URL}{user.pk}/" + "".join(f"{t}/" for t in tail)


def test_listing_needs_view_and_changing_needs_manage_users(staff, make_user):
    target = make_user("target")
    _, hr = staff("HR_OFFICER")  # users VIEW, no MANAGE_USERS
    assert hr.get(URL).status_code == 200
    assert (
        post(hr, URL, {"username": "x1", "email": "x1@e.org", "full_name": "X"}).status_code == 403
    )
    assert post(hr, uurl(target, "status"), {"status": "INACTIVE"}).status_code == 403
    assert patch(hr, uurl(target), {"full_name": "New"}).status_code == 403
    _, stores = staff("STOREKEEPER")
    assert stores.get(URL).status_code == 403
    assert stores.get(uurl(target)).status_code == 403


def test_anonymous_is_refused(new_client):
    assert new_client().get(URL).status_code in (401, 403)


def test_list_shows_the_columns_and_supports_search_filter_sort_paging(staff, make_user):
    _, admin = staff("ADMINISTRATOR", username="boss")
    a = make_user("alice", full_name="Alice Mwangi", email="alice@example.org")
    b = make_user("bob", full_name="Bob Kimaro", email="bob@example.org", status="INACTIVE")
    give_role(a, "FINANCE_OFFICER")
    rows = admin.get(URL).json()["results"]
    row = next(r for r in rows if r["username"] == "alice")
    assert set(row) >= {
        "full_name",
        "username",
        "email",
        "phone",
        "department",
        "position",
        "roles",
        "status",
        "created_at",
        "last_login",
    }
    assert [r["name"] for r in row["roles"]] == ["Finance Officer"]
    assert "password" not in row and "must_change_password" in row
    assert [r["username"] for r in admin.get(URL + "?q=kimaro").json()["results"]] == ["bob"]
    assert [r["username"] for r in admin.get(URL + "?status=INACTIVE").json()["results"]] == ["bob"]
    names = [r["username"] for r in admin.get(URL + "?ordering=-username").json()["results"]]
    assert names == sorted(names, reverse=True)
    role_id = a.user_roles.first().role_id
    assert [r["username"] for r in admin.get(f"{URL}?role={role_id}").json()["results"]] == [
        "alice"
    ]
    assert admin.get(URL + "?page_size=1").json()["count"] == 3
    assert admin.get(URL + "?department=not-a-uuid").json()["results"] == []
    assert admin.get(URL + "?ordering=password").status_code == 200  # unknown sort is ignored
    assert b.status == "INACTIVE"


def test_create_gives_a_one_time_password_and_forces_a_change(staff, new_client):
    admin_user, admin = staff("ADMINISTRATOR")
    response = post(
        admin, URL, {"username": "New.Person", "email": "n@example.org", "full_name": "New Person"}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    temporary = body.pop("temporary_password")
    assert len(temporary) >= 12
    user = User.objects.get(username="new.person")
    assert user.must_change_password and user.created_by == admin_user
    assert user.department_id is None and not user.user_roles.exists()
    assert temporary not in str(body)
    # The password works once, and a normal screen is closed until it is changed.
    fresh = new_client()
    assert sign_in(fresh, "new.person", temporary).status_code == 200
    assert fresh.get(URL).status_code == 403
    # Read it back: never shown again, never in the audit log.
    assert "temporary_password" not in admin.get(uurl(user)).json()
    assert temporary not in str(list(AuditEvent.objects.values_list("changes", "metadata")))
    assert AuditEvent.objects.filter(
        event_type=events.USER_CREATED, object_id=str(user.pk)
    ).exists()


def test_create_validates_and_refuses_duplicates(staff, make_user):
    _, admin = staff("ADMINISTRATOR")
    make_user("taken", email="taken@example.org")
    assert (
        post(
            admin, URL, {"username": "taken", "email": "z@example.org", "full_name": "Z"}
        ).status_code
        == 400
    )
    assert (
        post(
            admin, URL, {"username": "ok1", "email": "TAKEN@example.org", "full_name": "Z"}
        ).status_code
        == 400
    )
    assert (
        post(
            admin, URL, {"username": "Bad Name!", "email": "q@example.org", "full_name": "Z"}
        ).status_code
        == 400
    )
    assert (
        post(admin, URL, {"username": "ok2", "email": "nope", "full_name": "Z"}).status_code == 400
    )


def test_edit_changes_only_profile_fields_and_is_audited(staff, make_user):
    _, admin = staff("ADMINISTRATOR")
    target = make_user("target")
    response = patch(
        admin,
        uurl(target),
        {"full_name": "New Name", "phone": "+255712345678", "status": "LOCKED", "department": None},
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.full_name == "New Name" and target.status == "ACTIVE"
    event = AuditEvent.objects.filter(
        event_type=events.USER_UPDATED, object_id=str(target.pk)
    ).latest("id")
    assert event.changes["full_name"]["to"] == "New Name"


def test_deactivation_ends_sessions_and_reactivation_is_possible(staff, new_client, make_user):
    _, admin = staff("ADMINISTRATOR")
    victim = make_user("victim")
    browser = new_client()
    assert sign_in(browser, "victim").status_code == 200
    assert UserSession.objects.filter(user=victim, ended_at__isnull=True).exists()
    response = post(admin, uurl(victim, "status"), {"status": "INACTIVE", "reason": "left"})
    assert response.status_code == 200 and response.json()["status"] == "INACTIVE"
    assert not UserSession.objects.filter(user=victim, ended_at__isnull=True).exists()
    assert browser.get("/api/v1/auth/me/").status_code in (401, 403)
    assert sign_in(new_client(), "victim").status_code != 200
    post(admin, uurl(victim, "status"), {"status": "ACTIVE"})
    assert sign_in(new_client(), "victim").status_code == 200
    assert AuditEvent.objects.filter(
        event_type=events.USER_DEACTIVATED, object_id=str(victim.pk)
    ).exists()


def test_cannot_deactivate_yourself(staff):
    me, admin = staff("ADMINISTRATOR")
    assert post(admin, uurl(me, "status"), {"status": "INACTIVE"}).status_code == 403


def test_last_working_administrator_is_protected(staff, make_user):
    admin_user, admin = staff("ADMINISTRATOR")
    ed_user, ed = staff("EXECUTIVE_DIRECTOR")  # ED has users VIEW only
    give_role(ed_user, "ADMINISTRATOR")  # a second administrator, so ed can act
    assert post(ed, uurl(admin_user, "status"), {"status": "INACTIVE"}).status_code == 200
    # ed_user is now the only working administrator; nobody else can act on them,
    # but the service itself must refuse as well.
    from apps.accounts import services

    with pytest.raises(Exception, match="last working Administrator"):
        services.set_user_status(admin_user, ed_user, "INACTIVE")


def test_unlock_clears_a_lockout(staff, make_user, new_client, settings):
    _, admin = staff("ADMINISTRATOR")
    victim = make_user("victim")
    for _ in range(settings.TCOS_LOGIN_MAX_FAILURES):
        sign_in(new_client(), "victim", "wrong-password-123")
    assert sign_in(new_client(), "victim").status_code != 200
    assert post(admin, uurl(victim, "unlock"), {}).status_code == 200
    assert sign_in(new_client(), "victim").status_code == 200
    assert AuditEvent.objects.filter(event_type=events.USER_UNLOCKED).exists()


def test_admin_sends_a_reset_link_and_never_sees_a_password(
    staff, make_user, new_client, mailoutbox, django_capture_on_commit_callbacks
):
    me, admin = staff("ADMINISTRATOR")
    plain = make_user("plain", email="plain@example.org")
    browser = new_client()
    sign_in(browser, "plain")
    with django_capture_on_commit_callbacks(execute=True):
        response = post(admin, uurl(plain, "send-reset-link"), {})
    assert response.status_code == 200
    assert "password" not in str(response.json()).lower().replace("reset link", "")
    assert [m.to for m in mailoutbox] == [["plain@example.org"]]
    assert "/reset-password#token=" in mailoutbox[0].body
    event = AuditEvent.objects.filter(event_type=events.PASSWORD_RESET_LINK_SENT).get()
    assert event.actor_id == me.pk
    # The token never reaches the audit log.
    token = mailoutbox[0].body.split("#token=")[1].split()[0]
    assert token not in str(list(AuditEvent.objects.values_list("changes", "metadata")))
    # Not for yourself; and the old endpoint that returned a temporary password is gone.
    assert post(admin, uurl(me, "send-reset-link"), {}).status_code == 403
    assert post(admin, uurl(plain, "temporary-password"), {}).status_code == 404
    # Without MANAGE_USERS nothing is sent.
    _, hr = staff("HR_OFFICER", username="hr1")
    assert post(hr, uurl(plain, "send-reset-link"), {}).status_code == 403


def test_department_scope_limits_who_is_listed(staff, make_user, departments):
    from apps.rbac.models import Role, RolePermission, UserRole

    own = make_user("insider", department=departments["A"])
    make_user("outsider", department=departments["B"])
    viewer, client = staff("STOREKEEPER", department=departments["A"], username="viewer")
    role = Role.objects.create(code="DEPT_VIEWER", name="Department viewer")
    from apps.rbac.models import Permission

    RolePermission.objects.create(
        role=role,
        permission=Permission.objects.get(module="users", action="VIEW"),
        scope="DEPARTMENT",
    )
    UserRole.objects.create(user=viewer, role=role)
    names = {r["username"] for r in client.get(URL).json()["results"]}
    assert "insider" in names and "outsider" not in names
    assert client.get(uurl(User.objects.get(username="outsider"))).status_code == 404
    assert own.pk


def test_there_is_no_delete(staff, make_user):
    _, admin = staff("ADMINISTRATOR")
    target = make_user("target")
    assert delete(admin, uurl(target)).status_code in (403, 405)
    assert User.objects.filter(pk=target.pk).exists()

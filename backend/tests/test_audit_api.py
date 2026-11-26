"""The audit viewer API: who may see the log, filters, scope, read-only, and export."""

import csv
import io
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit import events, views
from apps.audit.models import AuditEvent
from apps.audit.service import record
from apps.rbac.models import UserRole

from .conftest import PASSWORD, delete, post, put, sign_in
from .test_rbac_management import make_role

LIST = "/api/v1/audit/events/"
EXPORT = "/api/v1/audit/export/"
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
MAY_VIEW = {"ADMINISTRATOR", "EXECUTIVE_DIRECTOR"}


def with_custom_role(make_user, new_client, role, username="custom", **user_kwargs):
    user = make_user(username, **user_kwargs)
    UserRole.objects.create(user=user, role=role)
    client = new_client()
    assert sign_in(client, username).status_code == 200
    return user, client


def results(response):
    assert response.status_code == 200, response.content
    return response.json()["results"]


@pytest.fixture
def viewer(make_user, new_client):
    return with_custom_role(make_user, new_client, make_role(("audit", "VIEW", "ALL")), "viewer")


# --- Who may see the log ---


def test_anonymous_users_get_401(new_client):
    for method, url in (("get", LIST), ("get", f"{LIST}1/"), ("get", "/api/v1/audit/event-types/")):
        assert getattr(new_client(), method)(url).status_code == 401, url


@pytest.mark.parametrize("role", ALL_ROLES)
def test_each_default_role_sees_the_log_only_if_it_should(staff, role):
    _, client = staff(role)
    expected = 200 if role in MAY_VIEW else 403
    assert client.get(LIST).status_code == expected
    assert client.get(f"{LIST}1/").status_code in ((404,) if expected == 200 else (403,))
    assert client.get("/api/v1/audit/event-types/").status_code == expected


@pytest.mark.parametrize("role", ALL_ROLES)
def test_no_default_role_may_export(staff, role):
    _, client = staff(role)
    assert post(client, EXPORT, {}).status_code == 403


def test_a_refusal_reveals_nothing_about_the_log(staff):
    _, client = staff("FINANCE_OFFICER")
    record(events.LOGIN_SUCCESS, actor_username="secretname")
    response = client.get(LIST)
    assert response.status_code == 403 and "secretname" not in response.content.decode()


def test_a_person_with_a_forced_password_change_cannot_read_the_log(make_user, new_client):
    user = make_user("fresh", must_change_password=True)
    UserRole.objects.create(user=user, role=make_role(("audit", "VIEW", "ALL")))
    client = new_client()
    sign_in(client, "fresh")
    assert client.get(LIST).status_code == 403


# --- Nothing can change or remove an event through the API ---


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_there_is_no_way_to_change_events_through_the_api(viewer, method):
    _, client = viewer
    event = record(events.LOGIN_SUCCESS, actor_username="x")
    before = AuditEvent.objects.count()
    token = {"HTTP_X_CSRFTOKEN": client.get("/api/v1/csrf/").cookies["csrftoken"].value}
    for url in (LIST, f"{LIST}{event.id}/"):
        response = getattr(client, method)(
            url, {"actor_username": "changed"}, format="json", **token
        )
        assert response.status_code in (403, 405), (method, url)
    assert AuditEvent.objects.count() == before
    event.refresh_from_db()
    assert event.actor_username == "x"


def test_export_endpoint_does_not_answer_get(viewer):
    _, client = viewer
    assert client.get(EXPORT).status_code in (403, 405)


# --- Listing, detail, filters ---


def test_list_is_newest_first_and_paginated(viewer):
    _, client = viewer
    for n in range(30):
        record(events.LOGIN_SUCCESS, actor_username=f"user{n:02d}")
    body = client.get(LIST).json()
    assert body["count"] >= 30 and len(body["results"]) <= 25
    ids = [row["id"] for row in body["results"]]
    assert ids == sorted(ids, reverse=True)
    assert body["next"]


def test_list_rows_are_summaries_and_detail_has_the_changes(viewer):
    _, client = viewer
    event = record(
        events.USER_UPDATED,
        actor_username="alice",
        object_type="accounts.User",
        object_id="abc",
        changes={"full_name": {"from": "A", "to": "B"}},
    )
    row = next(r for r in results(client.get(LIST)) if r["id"] == event.id)
    assert "changes" not in row and row["event_type"] == "USER_UPDATED"
    detail = client.get(f"{LIST}{event.id}/").json()
    assert detail["changes"] == {"full_name": {"from": "A", "to": "B"}}
    assert detail["event_hash"] == event.event_hash and detail["prev_hash"] == event.prev_hash


def test_unknown_event_is_404(viewer):
    assert viewer[1].get(f"{LIST}999999999/").status_code == 404


def test_event_types_list_for_the_filter(viewer):
    types = viewer[1].get("/api/v1/audit/event-types/").json()["results"]
    assert {"LOGIN_SUCCESS", "PERMISSION_CHANGED", "DATA_EXPORTED"} <= set(types)


@pytest.fixture
def mixed_events(viewer):
    record(
        events.LOGIN_SUCCESS, actor_username="alice", object_type="accounts.User", object_id="u1"
    )
    record(events.LOGIN_FAILED, actor_username="bob", success=False)
    record(events.ROLE_CREATED, actor_username="carol", object_type="rbac.Role", object_id="r1")
    return viewer[1]


def names(response):
    return {r["actor_username"] for r in results(response)} - {"viewer"}


def test_filter_by_text(mixed_events):
    assert names(mixed_events.get(LIST, {"q": "role_created"})) == {"carol"}
    assert names(mixed_events.get(LIST, {"q": "u1"})) == {"alice"}


def test_filter_by_actor(mixed_events):
    assert names(mixed_events.get(LIST, {"actor": "BO"})) == {"bob"}


def test_filter_by_one_or_several_event_types(mixed_events):
    assert names(mixed_events.get(LIST, {"event_type": "LOGIN_FAILED"})) == {"bob"}
    assert names(mixed_events.get(LIST, {"event_type": "login_failed,role_created"})) == {
        "bob",
        "carol",
    }


def test_filter_by_outcome(mixed_events):
    assert names(mixed_events.get(LIST, {"success": "false"})) == {"bob"}
    assert "bob" not in names(mixed_events.get(LIST, {"success": "true"}))
    assert mixed_events.get(LIST, {"success": "maybe"}).status_code == 400


def test_filter_by_object(mixed_events):
    assert names(mixed_events.get(LIST, {"object_type": "rbac.Role", "object_id": "r1"})) == {
        "carol"
    }


def test_filter_by_request_id(viewer):
    _, client = viewer
    response = client.get(LIST)
    request_id = response["X-Request-ID"]
    other = client.get(LIST, {"request_id": request_id})
    assert results(other) == []  # reading the log writes nothing, so nothing carries that id


def test_filter_by_date_range_is_inclusive_and_uses_the_local_day(viewer):
    _, client = viewer
    event = record(events.LOGIN_SUCCESS, actor_username="dated")
    local_day = timezone.localtime(event.occurred_at).date()
    day = local_day.isoformat()
    assert "dated" in names(client.get(LIST, {"date_from": day, "date_to": day}))
    tomorrow = (local_day + timedelta(days=1)).isoformat()
    yesterday = (local_day - timedelta(days=1)).isoformat()
    assert "dated" not in names(client.get(LIST, {"date_from": tomorrow}))
    assert "dated" not in names(client.get(LIST, {"date_to": yesterday}))
    assert client.get(LIST, {"date_from": "20/11/2026"}).status_code == 400
    assert client.get(LIST, {"date_to": "nonsense"}).status_code == 400


def test_the_day_boundary_follows_dar_es_salaam_not_utc(viewer):
    """An event at 22:30 UTC is already the next day in Tanzania (UTC+3)."""
    _, client = viewer
    event = record(events.LOGIN_SUCCESS, actor_username="late-night")
    late = timezone.now().replace(hour=22, minute=30, second=0, microsecond=0)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER USER")
        cursor.execute(
            "UPDATE audit_auditevent SET occurred_at = %s WHERE id = %s", [late, event.id]
        )
        cursor.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER USER")
    local_day = timezone.localtime(late).date()
    assert local_day > late.date()
    assert "late-night" in names(
        client.get(LIST, {"date_from": local_day.isoformat(), "date_to": local_day.isoformat()})
    )
    assert "late-night" not in names(client.get(LIST, {"date_to": late.date().isoformat()}))


# --- Scope: own and department ---


def test_a_viewer_limited_to_own_actions_sees_only_those(make_user, new_client):
    role = make_role(("audit", "VIEW", "OWN"))
    me, client = with_custom_role(make_user, new_client, role, "limited")
    other = make_user("someone-else")
    mine = record(events.LOGIN_SUCCESS, actor=me)
    theirs = record(events.LOGIN_SUCCESS, actor=other)

    seen = {r["id"] for r in results(client.get(LIST))}

    assert mine.id in seen and theirs.id not in seen
    assert client.get(f"{LIST}{theirs.id}/").status_code == 404  # existence not revealed
    assert client.get(f"{LIST}{mine.id}/").status_code == 200


def test_a_department_viewer_sees_that_departments_events(make_user, new_client, departments):
    role = make_role(("audit", "VIEW", "DEPARTMENT"))
    _, client = with_custom_role(
        make_user, new_client, role, "dept-viewer", department=departments["A"]
    )
    in_a = record(events.RECORD_UPDATED, department_id=departments["A"].pk, actor_username="x")
    in_b = record(events.RECORD_UPDATED, department_id=departments["B"].pk, actor_username="x")
    no_dept = record(events.RECORD_UPDATED, actor_username="x")

    seen = {r["id"] for r in results(client.get(LIST))}

    assert in_a.id in seen
    assert in_b.id not in seen and no_dept.id not in seen


def test_the_default_administrator_sees_everything(staff):
    _, client = staff("ADMINISTRATOR")
    event = record(events.RECORD_UPDATED, actor_username="x")
    assert event.id in {r["id"] for r in results(client.get(LIST))}


# --- Export ---


@pytest.fixture
def exporter(make_user, new_client):
    role = make_role(("audit", "VIEW", "ALL"), ("audit", "EXPORT", "ALL"))
    return with_custom_role(make_user, new_client, role, "exporter")


def rows_of(response):
    assert response.status_code == 200, response.content
    return list(csv.DictReader(io.StringIO(response.content.decode())))


def test_export_returns_csv_and_is_itself_audited(exporter):
    user, client = exporter
    record(events.ROLE_CREATED, actor_username="carol", object_type="rbac.Role", object_id="r1")
    before = AuditEvent.objects.count()

    response = post(client, EXPORT, {"event_type": "ROLE_CREATED", "date_from": "2020-01-01"})

    rows = rows_of(response)
    assert response["Content-Type"].startswith("text/csv")
    assert (
        "attachment" in response["Content-Disposition"] and response["Cache-Control"] == "no-store"
    )
    assert [r["actor"] for r in rows] == ["carol"]
    assert AuditEvent.objects.count() == before + 1
    logged = AuditEvent.objects.get(event_type="DATA_EXPORTED")
    assert logged.actor_id == user.pk and logged.metadata["rows"] == 1
    assert logged.metadata["filters"] == {"event_type": "ROLE_CREATED", "date_from": "2020-01-01"}


def test_export_with_view_permission_only_is_refused(viewer):
    assert post(viewer[1], EXPORT, {}).status_code == 403
    assert not AuditEvent.objects.filter(event_type="DATA_EXPORTED").exists()


def test_export_cannot_be_used_to_read_beyond_the_export_scope(make_user, new_client):
    role = make_role(("audit", "VIEW", "ALL"), ("audit", "EXPORT", "OWN"))
    me, client = with_custom_role(make_user, new_client, role, "own-exporter")
    record(events.LOGIN_SUCCESS, actor_username="someone-else")
    record(events.LOGIN_SUCCESS, actor=me)
    rows = rows_of(post(client, EXPORT, {}))
    assert {r["actor"] for r in rows} == {"own-exporter"}


def test_export_neutralises_spreadsheet_formulas(exporter):
    _, client = exporter
    record(events.LOGIN_FAILED, actor_username='=HYPERLINK("http://evil")', success=False)
    record(events.LOGIN_FAILED, actor_username="+cmd|' /C calc'!A0", success=False)
    record(events.LOGIN_FAILED, actor_username="@SUM(1+1)", success=False)
    actors = {r["actor"] for r in rows_of(post(client, EXPORT, {"event_type": "LOGIN_FAILED"}))}
    assert all(a.startswith("'") for a in actors if a[1:2] in "=+@" or a[:1] in "=+@-")
    assert not any(a[:1] in "=+-@" for a in actors)


def test_export_refuses_more_rows_than_the_limit_and_records_nothing(exporter, monkeypatch):
    _, client = exporter
    monkeypatch.setattr(views, "EXPORT_LIMIT", 2)
    for _ in range(3):
        record(events.LOGIN_FAILED, actor_username="many", success=False)
    response = post(client, EXPORT, {"event_type": "LOGIN_FAILED"})
    assert response.status_code == 400 and "Narrow the filters" in response.content.decode()
    assert not AuditEvent.objects.filter(event_type="DATA_EXPORTED").exists()


def test_export_ignores_unknown_filter_names(exporter):
    _, client = exporter
    post(client, EXPORT, {"event_type": "LOGIN_FAILED", "evil": "'; DROP TABLE x;--"})
    logged = AuditEvent.objects.get(event_type="DATA_EXPORTED")
    assert "evil" not in logged.metadata["filters"]


# --- Real use: what the administrator did shows up ---


def test_acceptance_actions_taken_in_the_app_appear_in_the_viewer(staff, new_client, make_user):
    _, admin_client = staff("ADMINISTRATOR", username="boss")
    target = make_user("target")
    post(admin_client, "/api/v1/rbac/roles/", {"name": "Visible Role"})
    other = new_client()
    sign_in(other, "target", "not-the-password-99")  # a failed attempt

    seen = results(admin_client.get(LIST))
    pairs = {(r["event_type"], r["actor_username"]) for r in seen}
    assert ("ROLE_CREATED", "boss") in pairs
    assert ("LOGIN_FAILED", "target") in pairs
    assert ("LOGIN_SUCCESS", "boss") in pairs
    assert target.username == "target"
    assert PASSWORD not in admin_client.get(LIST).content.decode()


def test_signing_in_as_the_viewer_does_not_expose_other_users_secrets(viewer, make_user):
    make_user("alice")
    client = APIClient()
    detail_text = viewer[1].get(LIST).content.decode()
    assert (
        "argon2" not in detail_text and "pbkdf2" not in detail_text and PASSWORD not in detail_text
    )
    assert (
        delete is not None and put is not None and client is not None
    )  # helpers imported for symmetry
    assert UserRole.objects.filter(user=viewer[0]).exists()

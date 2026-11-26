"""Every action that matters writes exactly one audit event, and never a secret."""

import json
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import services as account_services
from apps.accounts.models import User, UserSession
from apps.audit.models import AuditEvent
from apps.audit.service import verify_chain
from apps.rbac.models import Role

from .conftest import PASSWORD, delete, give_role, post, put, sign_in
from .test_rbac_management import cell, grants_url, make_role

NEW_PASSWORD = "a-brand-new-passphrase-42"


def events_of(response):
    """The events written while serving one request, found by its X-Request-ID header."""
    return list(AuditEvent.objects.filter(request_id=response["X-Request-ID"]).order_by("id"))


def only(response, event_type):
    found = events_of(response)
    assert [e.event_type for e in found] == [event_type], [e.event_type for e in found]
    return found[0]


@pytest.fixture
def admin(staff):
    user, client = staff("ADMINISTRATOR", username="boss")
    return user, client


# --- Request context --------------------------------------------------------------------


def test_every_response_carries_a_request_id(db, new_client):
    response = new_client().get("/api/v1/health/")
    assert len(response["X-Request-ID"]) >= 8


def test_a_plain_caller_supplied_request_id_is_kept_and_a_hostile_one_replaced(db, new_client):
    good = new_client().get("/api/v1/health/", HTTP_X_REQUEST_ID="trace-abc-12345")
    assert good["X-Request-ID"] == "trace-abc-12345"
    for hostile in ("x", "has space and <script>", "a" * 200, "line\nbreak-123456"):
        response = new_client().get("/api/v1/health/", HTTP_X_REQUEST_ID=hostile)
        assert response["X-Request-ID"] != hostile and len(response["X-Request-ID"]) <= 64


def test_events_store_the_request_ip_agent_and_id(new_client, make_user):
    make_user("alice")
    response = sign_in(new_client(), "alice", HTTP_USER_AGENT="TestAgent/9", REMOTE_ADDR="10.7.7.7")
    event = only(response, "LOGIN_SUCCESS")
    assert event.ip_address == "10.7.7.7" and event.user_agent == "TestAgent/9"
    assert event.request_id == response["X-Request-ID"]


# --- Sign-in and sessions ----------------------------------------------------------------


def test_successful_sign_in(new_client, make_user):
    user = make_user("alice")
    event = only(sign_in(new_client(), "alice"), "LOGIN_SUCCESS")
    assert event.actor_id == user.pk and event.actor_username == "alice" and event.success


def test_failed_sign_in_is_recorded_without_the_password(new_client, make_user):
    make_user("alice")
    response = sign_in(new_client(), "alice", "wrong-password-9999")
    event = only(response, "LOGIN_FAILED")
    assert event.success is False and event.actor_id is None and event.actor_username == "alice"
    assert event.metadata == {"reason": "BAD_CREDENTIALS"}
    assert "wrong-password-9999" not in json.dumps([event.changes, event.metadata])


def test_failed_sign_in_for_an_unknown_user_is_recorded_too(db, new_client):
    event = only(sign_in(new_client(), "nobody-here", "x" * 14), "LOGIN_FAILED")
    assert event.actor_username == "nobody-here" and event.object_id == ""


def test_a_blocked_attempt_is_a_separate_event_type(new_client, make_user):
    make_user("alice")
    for _ in range(5):
        sign_in(new_client(), "alice", "wrong-password-9999")
    event = only(sign_in(new_client(), "alice", PASSWORD), "LOGIN_BLOCKED")
    assert event.success is False and event.metadata["reason"] == "THROTTLED"


def test_sign_out(signed_in):
    user, client = signed_in("alice")
    event = only(post(client, "/api/v1/auth/logout/"), "LOGOUT")
    assert event.actor_id == user.pk


def test_signing_out_another_device_is_one_event_naming_the_device(signed_in, new_client):
    user, laptop = signed_in("alice")
    sign_in(new_client(), "alice", HTTP_USER_AGENT="Mozilla/5.0 (iPhone) Safari/604.1")
    other = UserSession.objects.exclude(session_key=laptop.session.session_key).get()

    response = delete(laptop, f"/api/v1/auth/sessions/{other.pk}/")

    event = only(response, "SESSION_ENDED")
    assert event.actor_id == user.pk and event.metadata["device"] == "Safari on iPhone"


def test_sign_out_all_other_devices_is_one_event_with_the_count(signed_in, new_client):
    user, laptop = signed_in("alice")
    for _ in range(2):
        sign_in(new_client(), "alice")
    event = only(post(laptop, "/api/v1/auth/sessions/end-others/"), "SESSIONS_ENDED")
    assert event.metadata["count"] == 2 and event.actor_id == user.pk


def test_sign_out_all_others_with_none_to_end_records_nothing(signed_in):
    _, client = signed_in("alice")
    assert events_of(post(client, "/api/v1/auth/sessions/end-others/")) == []


def test_changing_the_password_is_one_event_and_stores_no_password(signed_in, new_client):
    user, laptop = signed_in("alice")
    sign_in(new_client(), "alice")
    response = post(
        laptop,
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    event = only(response, "PASSWORD_CHANGED")
    assert event.metadata == {"ended_other_sessions": 1}
    everything = json.dumps(list(AuditEvent.objects.values_list("changes", "metadata")))
    assert PASSWORD not in everything and NEW_PASSWORD not in everything


# --- User accounts --------------------------------------------------------------------------


def test_creating_a_user_records_the_fields_but_not_the_password(admin):
    actor, _ = admin
    user = account_services.create_user(
        username="newbie",
        email="newbie@example.org",
        full_name="New Person",
        password=PASSWORD,
        created_by=actor,
    )
    event = AuditEvent.objects.get(event_type="USER_CREATED", object_id=str(user.pk))
    assert event.actor_id == actor.pk
    assert event.changes["username"] == {"from": None, "to": "newbie"}
    stored = json.dumps([event.changes, event.metadata])
    assert (
        PASSWORD not in stored and "argon" not in stored.lower() and "pbkdf2" not in stored.lower()
    )


def test_updating_a_user_records_only_what_changed(admin, make_user):
    actor, _ = admin
    target = make_user("target", full_name="Old Name")
    account_services.update_user(actor, target, full_name="New Name", phone="+255 700 000 000")
    event = AuditEvent.objects.get(event_type="USER_UPDATED")
    assert event.changes["full_name"] == {"from": "Old Name", "to": "New Name"}
    assert event.changes["phone"]["to"] == "+255 700 000 000"
    assert "email" not in event.changes and "department_id" not in event.changes


def test_a_department_cannot_be_edited_directly(admin, make_user, departments):
    """It follows the main staff assignment (Slice 4)."""
    actor, _ = admin
    target = make_user("target")
    with pytest.raises(ValidationError):
        account_services.update_user(actor, target, department=departments["A"])
    target.refresh_from_db()
    assert target.department_id is None


def test_an_update_that_changes_nothing_records_nothing(admin, make_user):
    actor, _ = admin
    target = make_user("target", full_name="Same")
    account_services.update_user(actor, target, full_name="Same")
    assert not AuditEvent.objects.filter(event_type="USER_UPDATED").exists()


def test_update_user_validates_and_refuses_other_fields(admin, make_user):
    actor, _ = admin
    first, second = make_user("first"), make_user("second")
    with pytest.raises(ValidationError):
        account_services.update_user(actor, second, email=first.email)
    with pytest.raises(ValidationError):
        account_services.update_user(actor, second, is_superuser=True)
    with pytest.raises(ValidationError):
        account_services.update_user(actor, second, email="not-an-email")
    assert not AuditEvent.objects.filter(event_type="USER_UPDATED").exists()


def test_deactivating_records_an_event_ends_sessions_and_blocks_sign_in(
    admin, signed_in, new_client
):
    actor, _ = admin
    target, target_client = signed_in("target")

    account_services.set_user_status(actor, target, "INACTIVE", reason="left the home")

    event = AuditEvent.objects.get(event_type="USER_DEACTIVATED")
    assert event.changes == {"status": {"from": "ACTIVE", "to": "INACTIVE"}}
    assert event.metadata["reason"] == "left the home"
    assert target_client.get("/api/v1/auth/me/").status_code == 401  # signed out at once
    assert sign_in(new_client(), "target").status_code == 401
    ended = AuditEvent.objects.get(event_type="SESSIONS_ENDED")
    assert ended.actor_id == actor.pk and ended.object_id == str(target.pk)


def test_reactivating_records_a_separate_event(admin, make_user):
    actor, _ = admin
    target = make_user("target", status="INACTIVE")
    account_services.set_user_status(actor, target, "ACTIVE")
    assert (
        AuditEvent.objects.filter(event_type="USER_ACTIVATED", object_id=str(target.pk)).count()
        == 1
    )


def test_setting_the_same_status_records_nothing(admin, make_user):
    actor, _ = admin
    target = make_user("target")
    account_services.set_user_status(actor, target, "ACTIVE")
    assert not AuditEvent.objects.filter(
        event_type__in=["USER_ACTIVATED", "USER_DEACTIVATED"]
    ).exists()


def test_nobody_can_deactivate_themselves(admin):
    actor, _ = admin
    with pytest.raises(PermissionDenied):
        account_services.set_user_status(actor, actor, "INACTIVE")
    actor.refresh_from_db()
    assert actor.status == "ACTIVE"


def test_the_last_working_administrator_cannot_be_deactivated(admin, make_user):
    _, _ = admin
    other = make_user("other-admin")
    give_role(other, "ADMINISTRATOR")
    first_admin = User.objects.get(username="boss")
    # Two administrators: one may be deactivated by the other.
    account_services.set_user_status(other, first_admin, "INACTIVE")
    # Only "other-admin" is left, so a third party cannot deactivate the last one.
    third = make_user("third")
    with pytest.raises(ValidationError, match="last working Administrator"):
        account_services.set_user_status(third, other, "INACTIVE")
    other.refresh_from_db()
    assert other.status == "ACTIVE"


def test_unknown_status_is_refused(admin, make_user):
    actor, _ = admin
    with pytest.raises(ValidationError):
        account_services.set_user_status(actor, make_user("tgt"), "BANISHED")


# --- Roles and permissions ---------------------------------------------------------------------


def test_creating_a_role_is_one_event_listing_its_grants(admin):
    _, client = admin
    response = post(
        client,
        "/api/v1/rbac/roles/",
        {"name": "Auditor Aide", "grants": [cell("reports", "VIEW", "ALL")]},
    )
    assert response.status_code == 201
    event = only(response, "ROLE_CREATED")
    assert event.changes["name"]["to"] == "Auditor Aide"
    assert event.changes["grants"]["to"] == ["reports.VIEW=ALL"]


def test_renaming_and_deactivating_a_role_records_the_diff(admin):
    _, client = admin
    role = make_role(("reports", "VIEW", "ALL"))
    response = client.patch(
        f"/api/v1/rbac/roles/{role.pk}/",
        {"name": "Renamed", "is_active": False},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert response.status_code == 200
    event = only(response, "ROLE_UPDATED")
    assert event.changes["name"]["to"] == "Renamed" and event.changes["is_active"]["to"] is False


def test_deleting_a_role_is_recorded_before_it_goes(admin):
    _, client = admin
    role = make_role()
    event_response = delete(client, f"/api/v1/rbac/roles/{role.pk}/")
    assert event_response.status_code == 204
    event = only(event_response, "ROLE_DELETED")
    assert event.object_id == str(role.pk) and event.changes["name"]["from"] == role.name


def test_a_permission_change_lists_added_removed_and_changed_cells(admin):
    _, client = admin
    role = make_role(
        ("reports", "VIEW", "ALL"), ("stores", "VIEW", "ALL"), ("stores", "EDIT", "ALL")
    )
    response = put(
        client,
        grants_url(role),
        {
            "grants": [
                cell("reports", "VIEW", "OWN"),  # scope narrowed
                cell("stores", "VIEW", "ALL"),  # unchanged
                cell("finance", "VIEW", "ALL"),  # added
            ]
        },
    )
    assert response.status_code == 200
    event = only(response, "PERMISSION_CHANGED")
    assert event.changes == {
        "added": ["finance.VIEW=ALL"],
        "removed": ["stores.EDIT=ALL"],
        "scope_changed": ["reports.VIEW: ALL -> OWN"],
    }
    assert event.object_id == str(role.pk)


def test_saving_an_unchanged_matrix_records_nothing(admin):
    _, client = admin
    role = make_role(("reports", "VIEW", "ALL"))
    response = put(client, grants_url(role), {"grants": [cell("reports", "VIEW", "ALL")]})
    assert response.status_code == 200 and events_of(response) == []


def test_assigning_and_revoking_a_role_names_who_what_and_where(admin, make_user, departments):
    _, client = admin
    target = make_user("target")
    role = Role.objects.get(code="STOREKEEPER")

    response = post(
        client,
        f"/api/v1/rbac/users/{target.pk}/roles/",
        {
            "role": str(role.pk),
            "department": str(departments["A"].pk),
            "valid_to": str(date.today() + timedelta(days=30)),
        },
    )
    assert response.status_code == 201
    assigned = only(response, "ROLE_ASSIGNED")
    assert assigned.object_id == str(target.pk) and assigned.metadata["role"] == "STOREKEEPER"
    assert assigned.department_id == departments["A"].pk

    revoked = delete(client, f"/api/v1/rbac/users/{target.pk}/roles/{response.json()['id']}/")
    assert only(revoked, "ROLE_REVOKED").metadata["role"] == "STOREKEEPER"


def test_refused_changes_write_no_event(admin):
    actor, client = admin
    admin_role = Role.objects.get(code="ADMINISTRATOR")
    before = AuditEvent.objects.count()
    response = put(client, grants_url(admin_role), {"grants": []})  # own role: refused
    assert response.status_code == 403
    assert AuditEvent.objects.count() == before


# --- The first administrator ---


def test_creating_the_first_administrator_is_audited_without_the_password(db, monkeypatch):
    monkeypatch.setenv("TCOS_ADMIN_USERNAME", "first.admin")
    monkeypatch.setenv("TCOS_ADMIN_EMAIL", "admin@example.org")
    monkeypatch.setenv("TCOS_ADMIN_FULL_NAME", "First Admin")
    monkeypatch.setenv("TCOS_ADMIN_PASSWORD", PASSWORD)
    call_command("create_initial_admin", stdout=StringIO())

    types = sorted(AuditEvent.objects.values_list("event_type", flat=True))
    assert types == ["ROLE_ASSIGNED", "USER_CREATED"]
    assert PASSWORD not in json.dumps(list(AuditEvent.objects.values_list("changes", "metadata")))
    assert verify_chain()["ok"]


# --- Secrets, everywhere ---


def test_no_secret_ever_reaches_the_audit_log(new_client, make_user, signed_in):
    """Run a busy sequence and search every stored byte for passwords, hashes and session keys."""
    user, client = signed_in("alice")
    session_key = client.session.session_key
    sign_in(new_client(), "alice", "typed-wrong-password-1")
    post(
        client,
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    post(client, "/api/v1/auth/sessions/end-others/")
    post(client, "/api/v1/auth/logout/")
    user.refresh_from_db()

    rows = list(
        AuditEvent.objects.values_list(
            "actor_username", "event_type", "object_id", "user_agent", "changes", "metadata"
        )
    )
    haystack = json.dumps(rows, default=str)
    for secret in (PASSWORD, NEW_PASSWORD, "typed-wrong-password-1", user.password, session_key):
        assert secret and secret not in haystack
    assert verify_chain()["ok"]


def test_the_chain_stays_valid_across_a_whole_workflow(admin, make_user, new_client):
    actor, client = admin
    target = make_user("target")
    post(client, "/api/v1/rbac/roles/", {"name": "Chain Role"})
    account_services.set_user_status(actor, target, "INACTIVE")
    sign_in(new_client(), "target")
    result = verify_chain()
    assert result["ok"] and result["checked"] == AuditEvent.objects.count() > 5


def test_audit_rows_cannot_be_removed_by_deleting_their_actor(admin):
    """Users are never hard-deleted; the audit trail must outlive them."""
    actor, _ = admin
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=actor.pk).delete()

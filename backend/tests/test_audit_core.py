"""The audit log itself: hash chain, immutability at every layer, redaction, rollback."""

import json

import pytest
from django.apps import apps as real_apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.accounts.models import LoginAttempt
from apps.audit import changes as audit_changes
from apps.audit import events
from apps.audit.hashing import GENESIS
from apps.audit.models import AuditEvent, ImmutableAuditError
from apps.audit.sanitise import REDACTED, sanitise
from apps.audit.service import record, verify_chain
from apps.core.management.commands.setup_database_roles import apply_roles
from tests.rbac_testapp.models import Record

TABLE = "audit_auditevent"
APP_ROLE = "tcos_app_test"


def quiet_user(username="alice"):
    """A user created without an audit event, so counts below start from zero."""
    from apps.accounts.models import User

    return User.objects.create(
        username=username, email=f"{username}@example.org", full_name=username
    )


@pytest.fixture
def three_events(db):
    user = quiet_user()
    return [record(events.LOGIN_SUCCESS, actor=user, metadata={"n": n}) for n in range(3)]


def settle():
    """Run deferred foreign-key checks now; PostgreSQL refuses ALTER/TRUNCATE while they wait."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def sql(statement, params=None):
    settle()
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])


def not_user_created():
    return AuditEvent.objects.exclude(event_type=events.USER_CREATED)


# --- Recording and the hash chain ------------------------------------------------------


def test_record_stores_what_happened(make_user):
    user = make_user("alice")
    event = record(
        events.USER_UPDATED,
        actor=user,
        object_type="accounts.User",
        object_id=user.pk,
        changes={"full_name": {"from": "A", "to": "B"}},
        metadata={"why": "test"},
    )
    event.refresh_from_db()
    assert event.actor_id == user.pk and event.actor_username == "alice"
    assert event.event_type == "USER_UPDATED" and event.success is True
    assert event.object_type == "accounts.User" and event.object_id == str(user.pk)
    assert event.changes == {"full_name": {"from": "A", "to": "B"}}
    assert event.occurred_at <= timezone.now()


def test_events_form_a_chain_starting_from_genesis(three_events):
    first, second, third = three_events
    assert first.prev_hash == GENESIS
    assert second.prev_hash == first.event_hash
    assert third.prev_hash == second.event_hash
    assert len({e.event_hash for e in three_events}) == 3


def test_an_intact_chain_verifies(three_events):
    result = verify_chain()
    assert result == {
        "ok": True,
        "checked": 3,
        "head": three_events[-1].event_hash,
        "broken_at": None,
    }


def test_an_empty_log_verifies(db):
    assert verify_chain()["ok"] is True and verify_chain()["checked"] == 0


def test_verify_command_reports_the_head_hash(three_events, capsys):
    call_command("verify_audit_chain")
    assert three_events[-1].event_hash in capsys.readouterr().out


def tamper(statement, params=None):
    """What a database owner could do: switch the trigger off, edit, switch it back on."""
    sql(f"ALTER TABLE {TABLE} DISABLE TRIGGER USER")
    try:
        sql(statement, params)
    finally:
        sql(f"ALTER TABLE {TABLE} ENABLE TRIGGER USER")


def test_editing_an_old_event_breaks_the_chain_at_that_event(three_events):
    tamper(
        f"UPDATE {TABLE} SET actor_username = 'someone-else' WHERE id = %s", [three_events[1].id]
    )

    result = verify_chain()

    assert result["ok"] is False and result["broken_at"] == three_events[1].id


def test_deleting_a_middle_event_is_detected(three_events):
    tamper(f"DELETE FROM {TABLE} WHERE id = %s", [three_events[1].id])

    result = verify_chain()

    assert result["ok"] is False and result["broken_at"] == three_events[2].id


def test_changing_the_details_of_an_event_is_detected(three_events):
    tamper(
        f"UPDATE {TABLE} SET changes = '{{\"x\": 1}}'::jsonb WHERE id = %s", [three_events[0].id]
    )
    assert verify_chain()["broken_at"] == three_events[0].id


def test_verify_command_fails_loudly_on_a_broken_chain(three_events):
    tamper(f"UPDATE {TABLE} SET success = false WHERE id = %s", [three_events[0].id])
    with pytest.raises(CommandError, match="BROKEN"):
        call_command("verify_audit_chain")


def test_chain_survives_unusual_text_and_numbers(make_user):
    user = make_user("alice")
    record(
        events.USER_UPDATED,
        actor=user,
        changes={"name": {"from": "Mwanaïsha ✓ é", "to": None}, "n": {"from": 1, "to": 2}},
        metadata={"nested": {"list": [1, "two", None, True]}},
    )
    record(events.LOGIN_FAILED, actor_username="nobody", success=False)
    assert verify_chain()["ok"] is True


# --- Immutability: application layer ----------------------------------------------------


def test_an_existing_event_cannot_be_saved_again(three_events):
    event = AuditEvent.objects.get(pk=three_events[0].pk)
    event.actor_username = "changed"
    with pytest.raises(ImmutableAuditError):
        event.save()


def test_an_event_cannot_be_deleted(three_events):
    with pytest.raises(ImmutableAuditError):
        AuditEvent.objects.get(pk=three_events[0].pk).delete()


@pytest.mark.parametrize("method", ["update", "delete"])
def test_querysets_refuse_bulk_changes(three_events, method):
    queryset = AuditEvent.objects.all()
    with pytest.raises(ImmutableAuditError):
        getattr(queryset, method)(**({"actor_username": "x"} if method == "update" else {}))


def test_bulk_update_create_and_update_or_create_are_refused(three_events):
    with pytest.raises(ImmutableAuditError):
        AuditEvent.objects.bulk_update(list(AuditEvent.objects.all()), ["actor_username"])
    with pytest.raises(ImmutableAuditError):
        AuditEvent.objects.bulk_create([AuditEvent(event_type="X")])
    with pytest.raises(ImmutableAuditError):
        AuditEvent.objects.update_or_create(event_type="X")


def test_events_cannot_be_created_around_the_service(db):
    """Direct creation would skip the hash chain, so it is refused."""
    with pytest.raises(ImmutableAuditError):
        AuditEvent.objects.create(
            occurred_at=timezone.now(), event_type="FAKE", prev_hash="x", event_hash="y"
        )
    assert AuditEvent.objects.count() == 0


# --- Immutability: database layer -------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {TABLE} SET actor_username = 'x'",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
    ],
)
def test_the_database_itself_refuses_changes_even_for_the_owner(three_events, statement):
    """Raw SQL, bypassing Django entirely, as the table owner."""
    with pytest.raises((InternalError, IntegrityError, ProgrammingError)) as caught:
        with transaction.atomic():
            sql(statement)
    assert "append-only" in str(caught.value)
    assert AuditEvent.objects.count() == 3


def as_app_role(statement, params=None):
    settle()
    with transaction.atomic():
        sql(f"SET LOCAL ROLE {APP_ROLE}")
        sql(statement, params)


@pytest.fixture
def app_role(db):
    apply_roles(APP_ROLE, "A" * 24)  # created inside the test transaction, rolled back after


def test_the_application_role_can_read_and_add_events(app_role, three_events):
    with transaction.atomic():
        sql(f"SET LOCAL ROLE {APP_ROLE}")
        record(events.LOGIN_SUCCESS, actor_username="written-as-app-role")
        assert AuditEvent.objects.count() == 4


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {TABLE} SET actor_username = 'x'",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
        f"ALTER TABLE {TABLE} DISABLE TRIGGER USER",
        f"DROP TRIGGER audit_event_no_row_change ON {TABLE}",
        f"DROP TABLE {TABLE}",
    ],
)
def test_the_application_role_has_no_way_to_change_the_log(app_role, three_events, statement):
    with pytest.raises(ProgrammingError, match="permission denied|must be owner"):
        as_app_role(statement)
    assert AuditEvent.objects.count() == 3


def test_the_application_role_still_works_for_ordinary_tables(app_role, make_user):
    user = make_user("alice")
    as_app_role("UPDATE accounts_user SET full_name = %s WHERE id = %s", ["New Name", user.pk])
    user.refresh_from_db()
    assert user.full_name == "New Name"


def test_the_application_role_cannot_rewrite_migration_history(app_role):
    with pytest.raises(ProgrammingError, match="permission denied"):
        as_app_role("DELETE FROM django_migrations")


def test_role_setup_is_repeatable_and_validates_its_input(app_role, monkeypatch):
    apply_roles(APP_ROLE, "B" * 24)  # second run: updates, does not fail
    monkeypatch.setenv("TCOS_APP_DB_PASSWORD", "short")
    with pytest.raises(CommandError, match="16 or more"):
        call_command("setup_database_roles")
    monkeypatch.setenv("TCOS_APP_DB_PASSWORD", "A" * 24)
    monkeypatch.setenv("TCOS_APP_DB_USER", "Bad Name; DROP")
    with pytest.raises(CommandError, match="lower-case"):
        call_command("setup_database_roles")


# --- A failed audit write rolls the change back ------------------------------------------


def boom(*args, **kwargs):
    raise RuntimeError("audit store unavailable")


def test_user_creation_is_rolled_back_if_the_audit_write_fails(db, monkeypatch):
    from apps.accounts.models import User
    from apps.accounts.services import create_user

    monkeypatch.setattr("apps.accounts.services.audit", boom)
    with pytest.raises(RuntimeError):
        create_user(
            username="ghost",
            email="g@example.org",
            full_name="Ghost",
            password="correct-horse-battery-9",
        )
    assert not User.objects.filter(username="ghost").exists()


def test_role_creation_is_rolled_back_if_the_audit_write_fails(make_user, monkeypatch):
    from apps.rbac.models import Role
    from apps.rbac.services import create_role

    monkeypatch.setattr("apps.rbac.services.audit", boom)
    with pytest.raises(RuntimeError):
        create_role(make_user("admin1"), name="Ghost Role")
    assert not Role.objects.filter(name="Ghost Role").exists()


def test_permission_change_is_rolled_back_if_the_audit_write_fails(make_user, monkeypatch):
    from apps.rbac.models import Role
    from apps.rbac.services import set_role_grants

    role = Role.objects.get(code="STOREKEEPER")
    before = sorted(role.grants.values_list("permission__module", "permission__action", "scope"))
    monkeypatch.setattr("apps.rbac.services.audit", boom)
    with pytest.raises(RuntimeError):
        set_role_grants(make_user("admin1"), role, [])
    after = sorted(role.grants.values_list("permission__module", "permission__action", "scope"))
    assert before == after and before


def test_a_status_change_is_rolled_back_if_the_audit_write_fails(make_user, monkeypatch):
    from apps.accounts.services import set_user_status

    target = make_user("target")
    monkeypatch.setattr("apps.accounts.services.audit", boom)
    with pytest.raises(RuntimeError):
        set_user_status(make_user("admin1"), target, "INACTIVE")
    target.refresh_from_db()
    assert target.status == "ACTIVE"


def test_sign_in_fails_if_it_cannot_be_audited(new_client, make_user, monkeypatch):
    from apps.accounts.models import UserSession

    from .conftest import sign_in

    make_user("alice")
    monkeypatch.setattr("apps.accounts.services.audit", boom)
    client = new_client()
    client.raise_request_exception = False
    response = sign_in(client, "alice")
    assert response.status_code == 500
    assert not UserSession.objects.exists()


# --- Secrets never appear -----------------------------------------------------------------


def test_secret_looking_fields_are_redacted_at_any_depth():
    cleaned = sanitise(
        {
            "password": "hunter2",
            "new_password": "hunter3",
            "nested": {
                "api_key": "abc",
                "token": "t",
                "ok": "visible",
                "deeper": [{"secret": "s"}],
            },
            "session_key": "k",
            "csrfmiddlewaretoken": "c",
            "recovery_codes": ["1", "2"],
            "Authorization": "Bearer x",
            "title": "fine",
        }
    )
    assert cleaned["password"] == cleaned["new_password"] == REDACTED
    assert cleaned["nested"]["api_key"] == cleaned["nested"]["token"] == REDACTED
    assert cleaned["nested"]["deeper"][0]["secret"] == REDACTED
    assert cleaned["nested"]["ok"] == "visible" and cleaned["title"] == "fine"
    assert cleaned["session_key"] == cleaned["csrfmiddlewaretoken"] == REDACTED
    assert cleaned["recovery_codes"] == cleaned["Authorization"] == REDACTED
    assert "hunter" not in json.dumps(cleaned)


def test_sanitise_makes_values_json_safe_and_bounded():
    import uuid
    from datetime import date
    from decimal import Decimal

    cleaned = sanitise(
        {
            "id": uuid.uuid4(),
            "day": date(2026, 11, 20),
            "amount": Decimal("12.50"),
            "long": "x" * 5000,
        }
    )
    json.dumps(cleaned)
    assert len(cleaned["long"]) < 2100
    assert sanitise(None) == {}


def test_secrets_passed_to_record_are_never_stored(make_user):
    user = make_user("alice")
    event = record(
        events.USER_UPDATED,
        actor=user,
        changes={"password": {"from": "old-secret-1", "to": "new-secret-2"}},
        metadata={"token": "tok-123"},
    )
    stored = json.dumps([event.changes, event.metadata])
    assert "old-secret-1" not in stored and "new-secret-2" not in stored and "tok-123" not in stored


# --- Generic hook for any model that opts in -----------------------------------------------


@pytest.fixture
def actor(make_user):
    return make_user("editor")


def test_create_update_archive_and_delete_are_recorded(actor, db):
    item = Record.objects.create(title="First", internal_note="private", created_by=actor)
    audit_changes.record_created(actor, item)

    before = audit_changes.snapshot(item)
    item.title = "Second"
    item.save()
    audit_changes.record_updated(actor, item, before)

    audit_changes.record_archived(actor, item)
    audit_changes.record_deleted(actor, item)

    types = list(not_user_created().order_by("id").values_list("event_type", flat=True))
    assert types == ["RECORD_CREATED", "RECORD_UPDATED", "RECORD_ARCHIVED", "RECORD_DELETED"]
    updated = AuditEvent.objects.get(event_type="RECORD_UPDATED")
    assert updated.changes == {"title": {"from": "First", "to": "Second"}}
    assert updated.object_type == "rbac_testapp.Record" and updated.object_id == str(item.pk)


def test_fields_a_model_excludes_never_appear_in_any_diff(actor, db):
    item = Record.objects.create(title="First", internal_note="private-note-xyz", created_by=actor)
    audit_changes.record_created(actor, item)
    before = audit_changes.snapshot(item)
    item.internal_note = "another-private-note"
    item.title = "Renamed"
    item.save()
    audit_changes.record_updated(actor, item, before)
    audit_changes.record_deleted(actor, item)

    everything = json.dumps(list(not_user_created().values_list("changes", flat=True)))
    assert "private-note-xyz" not in everything and "another-private-note" not in everything
    assert "internal_note" not in everything
    assert "Renamed" in everything  # ordinary fields are still recorded


def test_an_update_that_changes_nothing_writes_nothing(actor, db):
    item = Record.objects.create(title="Same", created_by=actor)
    before = audit_changes.snapshot(item)
    item.save()
    assert audit_changes.record_updated(actor, item, before) is None
    assert not_user_created().count() == 0


def test_record_events_carry_the_records_department(actor, db):
    from apps.organisation.models import Department

    department = Department.objects.create(code="D1", name="Dept One")
    item = Record.objects.create(title="Scoped", department=department, created_by=actor)
    audit_changes.record_created(actor, item)
    assert not_user_created().get().department_id == department.pk


# --- Backfill of Slice 1 login attempts -----------------------------------------------------


def test_backfill_turns_existing_login_attempts_into_a_valid_chain(db):
    user = quiet_user()
    now = timezone.now()
    LoginAttempt.objects.create(
        username_attempted="alice", user=user, success=True, ip_address="10.0.0.1", attempted_at=now
    )
    LoginAttempt.objects.create(
        username_attempted="bob", success=False, failure_reason="BAD_CREDENTIALS"
    )
    LoginAttempt.objects.create(username_attempted="bob", success=False, failure_reason="THROTTLED")
    assert AuditEvent.objects.count() == 0  # attempts above were created directly

    migration = __import__(
        "apps.audit.migrations.0003_backfill_login_attempts", fromlist=["forwards"]
    )
    historical = (
        MigrationExecutor(connection)
        .loader.project_state(
            [("audit", "0002_append_only_triggers"), ("accounts", "0002_user_department")]
        )
        .apps
    )
    migration.forwards(historical, None)

    rows = list(AuditEvent.objects.order_by("id"))
    assert sorted(r.event_type for r in rows) == ["LOGIN_BLOCKED", "LOGIN_FAILED", "LOGIN_SUCCESS"]
    assert all(r.metadata["backfilled"] for r in rows)
    assert verify_chain()["ok"] is True
    assert real_apps.get_model("audit", "AuditEvent").objects.count() == 3

"""Database-level immutability for audit_event.

A trigger refuses UPDATE, DELETE and TRUNCATE for every database role. (A table owner or
superuser could still drop the trigger, which is why the application should run as a
separate, restricted role: see ``manage.py setup_database_roles``, and the hash chain
detects the rest.)
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_event_refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % is not allowed', TG_OP;
END;
$$;

CREATE TRIGGER audit_event_no_row_change
    BEFORE UPDATE OR DELETE ON audit_audit_event_placeholder
    FOR EACH ROW EXECUTE FUNCTION audit_event_refuse_change();

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_audit_event_placeholder
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_refuse_change();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_audit_event_placeholder;
DROP TRIGGER IF EXISTS audit_event_no_row_change ON audit_audit_event_placeholder;
DROP FUNCTION IF EXISTS audit_event_refuse_change();
"""

TABLE = "audit_auditevent"


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        migrations.RunSQL(
            FORWARD.replace("audit_audit_event_placeholder", TABLE),
            REVERSE.replace("audit_audit_event_placeholder", TABLE),
        )
    ]

"""Database-level protection for the approval history (D-069).

* The history table refuses UPDATE, DELETE and TRUNCATE for every role.
* A review, approval or rejection by the person who raised the request is refused by the
  database itself, whatever the application does.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION approval_action_refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'approval history is append-only: % is not allowed', TG_OP;
END;
$$;

CREATE TRIGGER approval_action_no_row_change
    BEFORE UPDATE OR DELETE ON approvals_approvalaction
    FOR EACH ROW EXECUTE FUNCTION approval_action_refuse_change();

CREATE TRIGGER approval_action_no_truncate
    BEFORE TRUNCATE ON approvals_approvalaction
    FOR EACH STATEMENT EXECUTE FUNCTION approval_action_refuse_change();

CREATE FUNCTION approval_action_refuse_self_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.action IN ('REVIEW', 'APPROVE', 'REJECT') AND EXISTS (
        SELECT 1 FROM approvals_approvalrequest r
        WHERE r.id = NEW.request_id AND r.requester_id = NEW.actor_id
    ) THEN
        RAISE EXCEPTION 'a requester cannot % their own request', NEW.action;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER approval_action_no_self_decision
    BEFORE INSERT ON approvals_approvalaction
    FOR EACH ROW EXECUTE FUNCTION approval_action_refuse_self_decision();
"""

REVERSE = """
DROP TRIGGER IF EXISTS approval_action_no_self_decision ON approvals_approvalaction;
DROP FUNCTION IF EXISTS approval_action_refuse_self_decision();
DROP TRIGGER IF EXISTS approval_action_no_truncate ON approvals_approvalaction;
DROP TRIGGER IF EXISTS approval_action_no_row_change ON approvals_approvalaction;
DROP FUNCTION IF EXISTS approval_action_refuse_change();
"""


class Migration(migrations.Migration):
    dependencies = [("approvals", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

"""Create or refresh the restricted database role the application runs as.

Run as the database OWNER (the same connection that runs migrations), after migrating.
Safe to repeat; the Docker setup runs it on every start.

The application role may read and write ordinary tables but has only INSERT and SELECT
on ``audit_auditevent`` (no UPDATE, DELETE, TRUNCATE, TRIGGER) and cannot change
``django_migrations``. It is not the owner, so it cannot drop the audit trigger.

Environment: TCOS_APP_DB_PASSWORD (required, letters and digits, 16+ characters),
TCOS_APP_DB_USER (default ``tcos_app``).
"""

import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql

ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{2,40}$")
PASSWORD = re.compile(r"^[A-Za-z0-9]{16,128}$")
# Tables the application may only read and add to (never change or remove rows).
APPEND_ONLY_TABLES = ("audit_auditevent", "approvals_approvalaction")


class Command(BaseCommand):
    help = "Create/refresh the restricted application database role."

    def handle(self, *args, **options):
        role = os.environ.get("TCOS_APP_DB_USER", "tcos_app")
        password = os.environ.get("TCOS_APP_DB_PASSWORD", "")
        if not ROLE_NAME.match(role):
            raise CommandError(
                "TCOS_APP_DB_USER must be lower-case letters, digits and underscores."
            )
        if not PASSWORD.match(password):
            raise CommandError(
                "TCOS_APP_DB_PASSWORD must be 16 or more letters and digits "
                "(generate one with: openssl rand -hex 24)."
            )
        apply_roles(role, password)
        self.stdout.write(
            f"Database role '{role}' is set up (no update or delete on the audit log)."
        )


def apply_roles(role: str, password: str) -> None:
    ident = sql.Identifier(role)
    with connection.cursor() as wrapper:
        cursor = wrapper.cursor  # the raw psycopg cursor, which accepts composed SQL
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        exists = cursor.fetchone() is not None
        verb = "ALTER" if exists else "CREATE"
        cursor.execute(
            sql.SQL(
                verb
                + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            ).format(ident, sql.Literal(password))
        )
        cursor.execute("SELECT current_database()")
        database = sql.Identifier(cursor.fetchone()[0])
        statements = [
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, ident),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident),
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(ident),
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(ident),
            # Tables created by later migrations (run by this same owner) get the same rights.
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(ident),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(ident),
            # Only the owner changes the schema or the migration history.
            sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON django_migrations FROM {}").format(
                ident
            ),
        ]
        for table in APPEND_ONLY_TABLES:  # the audit log and approval history: add and read only
            statements.append(
                sql.SQL("REVOKE ALL ON {} FROM {}").format(sql.Identifier(table), ident)
            )
            statements.append(
                sql.SQL("GRANT SELECT, INSERT ON {} TO {}").format(sql.Identifier(table), ident)
            )
        for statement in statements:
            cursor.execute(statement)

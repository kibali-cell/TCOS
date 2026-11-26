# TCOS administrator setup

This file grows with each slice. It covers what an administrator must do to run TCOS safely.

## 1. Secrets in `.env`

Copy `.env.example` to `.env` and fill in the values. Never share or commit `.env`.

| Setting | What it is |
|---|---|
| `POSTGRES_PASSWORD` | Password of the database owner. Used only to migrate and set up roles. |
| `TCOS_APP_DB_PASSWORD` | Password of the restricted account the running server uses. Different from the owner's. |

Generate each with `openssl rand -hex 24`. Use letters and digits only (16 to 128 characters).

## 2. Why the server has its own database account

The audit log is evidence of who did what. To keep it trustworthy, the running server connects as `tcos_app`, which can read and add to the audit log but cannot change or remove anything in it, and cannot change the migration history. Docker Compose does this for you on every start:

1. Run migrations as the owner.
2. Run `manage.py setup_database_roles` (creates or refreshes `tcos_app`; safe to repeat).
3. Start the server as `tcos_app`.

Commands you run yourself, such as `docker compose exec backend python manage.py create_initial_admin`, use the owner account.

If you change `TCOS_APP_DB_PASSWORD`, restart the stack; the role's password is updated on start.

## 3. Checking the audit log is intact

```bash
docker compose exec backend python manage.py verify_audit_chain
```

It prints "Audit chain intact" with the number of events and a **head hash**, or names the first event that was altered or removed.

Recommended: record the head hash somewhere outside the server (for example in the monthly report to the board). The chain detects any later edit, deletion or reordering. A person with full database superuser access could rewrite the whole chain, and an off-site head hash is what exposes that.

## 4. Who can see the audit log

By default only the Administrator and the Executive Director can view it. Nobody can export it. To allow export, open **Roles and permissions**, choose a role, and set **Audit Log: Export**. Exports are recorded in the log themselves.

## 5. Not covered yet

User management screens, password reset, two-factor sign-in, device registration and backup procedures arrive in later slices and will be added here.

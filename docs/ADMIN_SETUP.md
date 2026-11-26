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

## 5. Setting up the organisation

Open **Organisation** in the menu (you need Administration access).

1. The system starts with twelve departments, one for each part of TCOS, and a head position for each, with an Executive Director position at the top. Treat these as a starting point: rename, nest or archive them to match the real home.
2. Under **Positions**, add the posts that exist (for example Cook, Matron, Teacher) and who each one reports to.
3. Under **Staff**, assign each person to a position. A person's first assignment is their **main** one: it decides which department's records they can reach if their role is limited to their department. To move someone, use **Transfer**; to give them extra duties, assign another position (it stays additional).
4. Under **Departments**, name each head. A head must already hold a position in that department.
5. Under **Approval chains**, set who approves requests from each department, in order. These are stored now and start to be used when the Approval Centre is added.

Archiving is blocked while people or reporting lines depend on a record; the screen says what to change first. Everything you change is recorded in the audit log.

You can re-create any missing starting departments with `docker compose exec backend python manage.py seed_organisation`. It never changes what you have edited.

## 6. Not covered yet

User management screens, password reset, two-factor sign-in, device registration and backup procedures arrive in later slices and will be added here.

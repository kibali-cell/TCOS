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

## 6. Approvals, sensitive roles and TZS limits (Slice 5)

- **First Executive Director or Board Member.** Sensitive roles need another person's approval, so the first holders must be given from the server console: `python manage.py grant_role_from_console USERNAME EXECUTIVE_DIRECTOR --reason "Initial setup"`. It is audited. Do the same for at least one `BOARD_MEMBER`: the Administrator, Executive Director and Board Member roles can only be approved by a Board Member.
- **Giving a sensitive role later:** an administrator raises a role-grant request (Approvals, "Grant a sensitive role"); a different person approves it. The roles screen shows which roles are sensitive and why.
- **Approval routes:** set a chain per department (Organisation, Approval chains). Without one, requests go to the Executive Director.
- **TZS limits:** open Approvals, Limits. The numbers shown are provisional and **not ratified**. Propose the real ones; an Executive Director or Board Member who did not propose them approves.
- **Access review:** Administration, Access review. Check it regularly. Set `TCOS_HOSTING_REGION` once the hosting region is decided.
- **Also see** `docs/DATA_SOVEREIGNTY.md`.

## 7. Users and dashboards (Slice 6)

- **Users:** Administration, Users. Create a person, then give them a role (sensitive roles through the Approval Centre) and a main post in Organisation, which sets their department.
- **First sign-in:** the new person gets a temporary password from the screen, shown once. Pass it on privately (in person or a call, not a group chat). They must change it at first sign-in.
- **Someone leaves:** deactivate the account; their sessions end at once. Accounts are never deleted, so history stays correct.
- **Locked out:** open the person and press "Clear sign-in lockout".
- **Forgotten password of someone with a sensitive role** (Administrator, Executive Director, Board Member, Finance Officer and so on): not possible from the screen, by design (D-072). Ask the server operator until reset by e-mail arrives.
- **Dashboard numbers:** figures marked "Reference figure (not yet verified)" are the starting figures from the institution (85 children, 42 residential, 43 outreach, 15 employees), not counted from records. Employees become a live count once staff posts are entered.
- **Printing:** use the Print button on the users list, the dashboard and the department dashboard.

## 8. Not covered yet

User management screens, password reset, two-factor sign-in, device registration and backup procedures arrive in later slices and will be added here.

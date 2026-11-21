# TCOS Phase One: Staged Prompts

How to use: start a fresh session in the project folder with `CLAUDE.md` and `docs/SCHEMA.md` present. Paste **one** prompt at a time. After each slice, review the report, try the result yourself, then approve the next slice. Do not paste several prompts together.

Every prompt below assumes the standing rules in `CLAUDE.md`.

**Hybrid cloud and offline:** TCOS must keep working through internet interruptions without weakening security. The full design is `docs/HYBRID_ARCHITECTURE.md`. Slices 1 to 7 are built "sync-ready" so offline support can be added without rework; Slices 8 to 11 add devices, the sync server, the offline client and the offline controls; Slice 12 verifies everything. Decisions made so far: English only; users may hold several roles.

**Sync-ready conventions (apply in every slice from 1 to 7):** for any model that may later be available offline, use a client-generatable UUID primary key, an integer `version` (starts at 1, increments on every change), `updated_at`, `updated_by` and archival instead of deletion; make changes only through service functions (never directly in views) so a change log entry can be written in the same transaction; never let client-supplied values decide permissions, approvers, official numbers or status. Do not build any sync or offline code in these slices.

---

## Slice 0: Project setup (greenfield)

```
Read CLAUDE.md and docs/SCHEMA.md fully.

This is a brand-new project. First confirm the working directory is empty or contains only CLAUDE.md and docs/. If anything else exists, stop and tell me what you found.

Set up the project foundation only (no business features yet):
1. Initialise a Git repository with a sensible .gitignore (no secrets, no uploaded files, no .env). Use a neutral organisational commit identity placeholder; do not use any personal name or email in files.
2. Create the repository layout described in CLAUDE.md section 5, with the Django project (config/ with base/dev/prod settings) and the empty app packages: core, accounts, rbac, organisation, approvals, audit, dashboard.
3. Create docker-compose.yml with PostgreSQL, the Django backend and the React frontend dev server; a .env.example with every variable documented; and a README with exact commands to start everything from scratch.
4. Create the React app (TypeScript) with routing, a placeholder layout and an API client that handles CSRF and session cookies.
5. Add test tooling: pytest-django, Vitest, Playwright, linters (ruff, eslint), and a Makefile or scripts to run everything.
6. Create docs/DECISIONS.md, docs/STATUS.md and docs/TEST_REPORT.md as living documents.
7. Add a health-check endpoint /api/v1/health/ that confirms database connectivity.

Do NOT create the User model yet beyond what is needed to run; that belongs to Slice 1 and must exist before the first real migration.

Acceptance: `docker compose up` brings up all services from a clean checkout; health endpoint returns OK; test commands run (even if few tests); lint passes.
Then report per CLAUDE.md section 9 and stop.
```

---

## Slice 1: Custom user, authentication, React shell

```
Read CLAUDE.md and docs/SCHEMA.md (accounts section). Implement Slice 1.

Backend (apps/accounts):
1. Custom User model exactly as in SCHEMA.md, set as AUTH_USER_MODEL before any other migration is created.
2. Session-based login and secure logout with CSRF protection. Endpoints: login, logout, me (returns profile; permissions will be added in Slice 2).
3. Password policy (length, common-password and similarity validation), Argon2 or PBKDF2 hashing.
4. Login attempt recording in the login_attempt table, lockout after repeated failures (configurable), generic error messages, rate limiting.
5. A management command `create_initial_admin` that creates the first administrator interactively or from environment variables. No default or hard-coded credentials anywhere.
6. Session management: idle (30 min) and absolute (12 h) timeouts. REQUIRED (owner decision): list my active sessions, end one other session, and "sign out all other devices"; changing the password ends all other sessions. A new sign-in always starts a fresh session key.

Frontend:
7. Login page, authenticated app shell (responsive sidebar on desktop, drawer on mobile), logout, protected routes, session-expiry handling.
8. Navigation lists all twelve modules; modules not yet built show a clear "Not yet available" page, not a fake screen.

Tests: user creation, login success/failure, lockout, logout invalidates session, protected endpoints reject anonymous users, password validation, CSRF enforcement. Frontend: login form behaviour and route protection.

Acceptance: I can create the first admin from the command line, log in on a desktop and on a phone-sized viewport, and log out. Failed logins are recorded.
Note: audit events for logins will be wired in Slice 3; for now record in login_attempt and state this in STATUS.md.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 2: Roles, permissions, scoped access

```
Read CLAUDE.md and docs/SCHEMA.md (rbac section). Implement Slice 2.

1. Models and migrations: role, permission (module + action), role_permission (with scope), user_role (with optional department scope and validity dates), record_grant.
2. Seed (via data migration or management command, idempotent) the permissions for every module and every action in CLAUDE.md section 6, and the 11 default roles. Seeded roles are editable; mark them is_system so they cannot be deleted. Choose sensible default grants per role, list them in docs/DECISIONS.md and flag them for my review. Do not give any role blanket access except Administrator for system modules.
3. A single central permission engine in rbac/permissions: `can(user, module, action, obj=None)` plus a DRF permission class and a queryset filter helper, honouring scope ALL / DEPARTMENT / OWN / ASSIGNED and record grants. A user may hold several roles: effective permission is the union of all active roles (valid dates respected), using the widest scope per module and action. Every DRF view must use it. Add a test that fails if any API view is missing a permission class.
4. APIs to manage roles, assign permissions independently, assign roles to users (authorised admins only, MANAGE_USERS).
5. /auth/me/ returns the user's effective permissions for the frontend.
6. Frontend: roles and permissions management screen (matrix of module x action with scope selector); navigation filtered by permissions.

Tests (most important part of this slice): a parametrised test suite that logs in as each of the 11 roles and attempts allowed and forbidden actions; department-scope tests (user from Dept A cannot see Dept B records); record-grant tests; "UI hidden is not secure" tests calling the API directly; an escalation test (a user cannot grant themselves permissions they lack); multi-role tests (union of permissions, widest scope wins, a department-restricted role combined with an unrestricted one, an expired role stops applying, removing one role leaves the others intact).

Acceptance: changing a role's permission in the screen immediately changes API behaviour, verified by tests.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 3: Audit log

```
Read CLAUDE.md and docs/SCHEMA.md (audit section). Implement Slice 3.

1. audit_event table as designed, with the hash-chain fields if I approved them in SCHEMA.md review.
2. Database-level immutability: a migration that creates a trigger raising an exception on UPDATE and DELETE, and a restricted application database role with no UPDATE/DELETE/TRUNCATE on the audit table. Document how it is set up in ADMIN_SETUP.md.
3. An `audit.record(...)` service used everywhere. Wire it into: successful and failed logins, logout, user create/update/activate/deactivate, role and permission changes, role assignments, and a generic hook for create/modify/archive of any model that opts in (so later modules inherit it). Exclude secrets and sensitive fields from change diffs.
4. Make audit writes part of the same database transaction as the change where possible, so a change cannot occur without its audit event.
5. Audit viewer: searchable, filterable (actor, event type, date, object), paginated, read-only; export is itself an audited action requiring EXPORT permission. No edit or delete endpoints exist.
6. Backfill: connect Slice 1 login_attempt recording to audit events.

Tests: each listed event type produces exactly one audit event; audit rows cannot be updated or deleted via ORM, raw SQL as the app role, or API (assert the DB raises); failure to write audit rolls back the change; sensitive fields never appear in diffs; ordinary users cannot view the audit log.

Acceptance: I can perform actions in the UI and see them in the audit viewer; I cannot alter them by any route.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 4: Organisation structure

```
Read CLAUDE.md and docs/SCHEMA.md (organisation section). Implement Slice 4.

1. Models and migrations: department (with optional parent), position, staff_assignment, with department heads and reporting relationships as in SCHEMA.md. These are reference data that devices will later read offline, so follow the sync-ready conventions. Constraints: no reporting cycles, one primary assignment per user at a time, department code unique.
2. Seed an initial editable structure containing the departments matching the twelve modules (flag the proposed structure in DECISIONS.md for my review). Do not invent named people.
3. APIs and screens for authorised administrators: create/edit/archive departments and positions, set department heads, assign staff, define reporting lines, view an organisation chart (tree view that works on mobile).
4. Approval hierarchies: define per-department approver chains by position or role (stored now, consumed by the Approval Centre in Slice 5).
5. All changes audited and permission-checked. Archiving a department with active staff or open requests must be blocked with a clear message.
6. Connect department to the RBAC department scope from Slice 2 so department restrictions use real assignments.

Tests: cycle prevention, archive blocking, scope integration (moving a user to another department changes what they can see), audit events, permissions.

Acceptance: I can build and change the structure from the UI and the permissions follow it.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 5: Approval Centre

```
Read CLAUDE.md and docs/SCHEMA.md (approvals section). Implement Slice 5.

1. Models and migrations: approval_workflow and steps, approval_request, approval_action (append-only history), attachments via the core document model, and a concurrency-safe request-number generator (format TCOS-REQ-YYYY-NNNNNN, never reused).
2. State machine enforced server-side: DRAFT -> SUBMITTED -> UNDER REVIEW -> APPROVED / REJECTED; CANCELLED allowed from DRAFT/SUBMITTED/UNDER REVIEW by the requester or an authorised user. Illegal transitions return errors. Terminal states are final.
3. Every request has: unique number, requesting employee, department, description, submission date, assigned approver, status, comments, decision date.
4. Approver resolution from the organisation hierarchy built in Slice 4. Multi-step chains supported if SCHEMA.md approved it; otherwise single step, and say so.
5. Separation of duties: requester can never review, approve or reject their own request, enforced in the service layer and verified by test; also handle the case where the only possible approver is the requester (escalate to next level or block with a clear message, as decided in DECISIONS.md).
6. Notifications to approvers and requesters (in-app, stored in the notification table; email only if email is configured).
7. Every transition writes an approval_action row and an audit event, in the same transaction.
8. Screens: My Requests, Pending My Approval, All Requests (by permission), request detail with full history, create/submit/cancel, approve/reject with mandatory comment on rejection. Mobile friendly.
9. Sync-ready design (no sync code yet): approval_request follows the sync-ready conventions and includes `local_reference`, `risk_level`, `created_offline`, `origin_device_id`, `client_created_at` and `version` as in SCHEMA.md. Creating a draft with a caller-supplied UUID must be idempotent. Official request numbers are assigned only by the server at submission. The decision functions (review, approve, reject) must be separate from create/submit/edit functions so Slice 11 can refuse them from any offline path. The approver is always resolved by the server from the current hierarchy; ignore any approver supplied by the caller on submission.

Tests: every legal and illegal transition; self-approval attempts via API; wrong-approver attempts; department restrictions; concurrent approvals of the same request; request number uniqueness under parallel creation; history immutability; notifications created.

Acceptance: I can submit a request as one user and approve it as another, see the full history, and confirm the first user cannot approve it.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 6: Dashboard, user management, responsive layout

```
Read CLAUDE.md and docs/SCHEMA.md. Implement Slice 6.

1. User management dashboard: table with full name, username, email, phone, department, position, assigned role, account status, date created, last login. Search, filter, sort, pagination; create user, edit, activate/deactivate (never hard delete), assign role and department. Requires MANAGE_USERS. Deactivation ends the user's active sessions. Cannot deactivate the last active administrator.
2. Central dashboard (/api/v1/dashboard/ and screen): total children, residential children, outreach children, total employees, active projects, pending approvals, financial summaries (only for users with finance VIEW permission, enforced server-side), recent activities (from audit, filtered to what the user may see), institutional notifications.
3. Use the reference figures (85 / 42 / 43 / 15) stored in core_reference_figure. The API must return, for each number, its value and its source: "reference" or "live". Display a clear "Reference figure (not yet verified)" label on any reference-sourced number. Modules not built yet (children, projects, finance) show reference or "No data yet", never invented numbers.
4. Department-specific dashboards: a framework with a department dashboard route showing that department's pending approvals, staff count and recent activity. Module-specific widgets are for later phases.
5. Responsive polish across all existing screens at 360px, 768px and 1280px; printable view for the dashboard and the user list.

Tests: user management permissions; last-admin protection; deactivation ends sessions; dashboard values come from the database; finance figures hidden from unauthorised users at the API level; reference vs live labelling; Playwright mobile-viewport checks of login, navigation, approvals and user list.

Acceptance: dashboard loads for different roles with different content; nothing displayed is fabricated.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 7: Password reset, two-factor, document uploads

```
Read CLAUDE.md and docs/SCHEMA.md. Implement Slice 7.

1. Password reset: request and confirm flow using single-use, hashed, time-limited tokens; identical responses whether or not the account exists; rate limited; resetting ends all existing sessions; audited. Email through a configurable backend (console in dev, SMTP via environment variables in production). Document the required SMTP settings in ADMIN_SETUP.md. An administrator-initiated reset must not let the administrator see the new password.
2. Optional TOTP two-factor: enrol with QR code, confirm with a code, hashed one-time recovery codes, disable with re-authentication, administrators can require 2FA per role (setting). Secrets stored encrypted. Login flow handles the 2FA step; failures are audited and rate limited.
3. Document uploads (online-only in Phase One; see HYBRID_ARCHITECTURE.md section 4) (core document model): private storage outside any public/static path; allowed types and size limits configurable; SHA-256 recorded; random storage keys; downloads only via an authenticated endpoint that checks permission on the parent record; classification field (e.g. NORMAL, CONFIDENTIAL, CHILD_SENSITIVE); virus scanning hook (stub clearly marked if ClamAV is not set up); upload, download and archive are audited. Wire attachments into approval requests.
4. Frontend: forgot/reset password pages, 2FA enrolment and login step, reusable upload component with progress and error states.

Tests: reset token single use, expiry, enumeration resistance; sessions invalidated after reset; 2FA enrol/login/recovery/disable; wrong code lockout; uploaded files unreachable without authentication and without permission; file type/size rejection; path traversal attempts; direct URL guessing fails.

Acceptance: I can reset a password by email, enable 2FA, and attach a file to a request that only permitted users can download.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 8: Device registry, enrolment and revocation

```
Read CLAUDE.md, docs/HYBRID_ARCHITECTURE.md (sections 5 and 10) and docs/SCHEMA.md (section 8A). Implement Slice 8.

1. Models and migrations: device, device_enrolment_code, device_session. Every login session is recorded in device_session (device is null for unregistered devices).
2. Administrator APIs and screens (new permission module `devices`; Administrator role by default): register a device (name, type computer/tablet/smartphone, assigned user), issue a one-time enrolment code (shown once, stored hashed, expires), list devices with status, last seen, last sync, lease expiry, revoke with a reason, extend a lease, view a device's history.
3. Enrolment: the user signs in on the device and enters the code; the device generates a non-extractable key pair (Web Crypto) and registers only the public key; the server marks the device ACTIVE. Implement challenge-response proof of possession (the device signs a server challenge) for later sync requests, and record the exact mechanism in DECISIONS.md.
4. Revocation: ends all of the device's sessions immediately, refuses every further request from it, queues a wipe instruction delivered on its next contact, and is audited. Deactivating a user or resetting a password also ends that user's device sessions and forces re-authentication.
5. Offline lease: each successful check-in renews lease_expires_at (period from the owner's decision D-H2, default 7 days). An expired device must re-authenticate online and receives a wipe instruction.
6. Server side of secure logout and local clearing: logout response tells the client whether to keep or clear local data (clear by default on unregistered devices); a clear-local-data hook that removes any device-bound key material.
7. /auth/me/ reports whether the current device may use offline mode. Unregistered devices can sign in online but are never offline-enabled.

Tests: enrolment code is single use, expires, and only its hash is stored; wrong or reused code fails; revoking ends sessions immediately and every authenticated endpoint then refuses the device; wipe instruction is delivered and acknowledged; user deactivation and password reset end device sessions; lease expiry; only authorised administrators can register or revoke; a request signed with a different key is rejected; every action is audited.

Acceptance: I can register a phone, enrol it, revoke it, and watch it lose access immediately.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 9: Synchronisation server

```
Read CLAUDE.md, docs/HYBRID_ARCHITECTURE.md (sections 4, 6, 7, 8) and docs/SCHEMA.md (section 8A). Implement Slice 9 (backend only; the offline client is Slice 10).

1. Sync policy registry in code: each syncable model declares its serializer, permission scoping via the central RBAC engine, which operations are allowed offline, conflict strategy (field-level merge or server-wins-manual), classification handling and which actions are online-only. A model with no policy is online-only. A test must fail if a syncable model lacks a policy.
2. Change log (sync_change): appended in the same transaction as the change by the service functions, with a transaction-level advisory lock so log order equals commit order. Register departments, positions, staff assignments (read only), approval requests (read; create, edit draft and submit), and notifications (read, mark read). CHILD_SENSITIVE records are excluded unless the owner decided otherwise (D-H1).
3. Pull endpoint: cursor-based; returns only what this user and this device may see now; purge instructions for records that left scope; tombstones for archived records; full snapshot on first sync or invalid cursor; paginated; carries a protocol version.
4. Push endpoint: ordered mutations, each in its own transaction. For each: device and user active; permissions re-checked now; policy allows the operation offline; validation and state machine; apply or return applied / merged / conflict / rejected (plain-language reason) / requires_online. Idempotent through unique (device_id, mutation_id): a resent mutation returns its stored outcome. Idempotent creates on an existing client UUID. Server time is authoritative; client time is stored but never used for ordering or authority. Server-assigned values are never taken from the client.
5. Conflicts: record versions; merge only when policy allows and changed fields do not overlap; otherwise create a sync_conflict and apply nothing; resolution endpoints (keep server, apply mine, edit) where a resolution is a new validated, audited mutation.
6. sync_event history: append-only (same database protection as the audit log); endpoints for a user's own history and for administrators' filtered view.
7. Quarantine: mutations from revoked or expired devices are stored as QUARANTINED and never applied.
8. Rate limits and payload size limits on sync endpoints.

Tests: replaying a push twice; a retry after the server applied a change but the response was lost; duplicate create with the same entity id; conflict detection, non-overlapping merge, and each resolution path; permissions re-checked at sync time (a change by a user who lost the permission is rejected); permission reduction purges on next pull; ordering (a pulling client never skips a change while writers overlap); 50 or more parallel pushes from different devices with no lost or duplicated change; protocol version mismatch; revoked-device quarantine; every outcome audited and listed in sync history; no sensitive content in logs.

Acceptance: I can drive the sync API with a test client, simulate two devices, and see conflicts, duplicates and revocation handled correctly.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 10: Offline client

```
Read CLAUDE.md and docs/HYBRID_ARCHITECTURE.md (sections 3, 5, 6, 8, 13). Implement Slice 10.

1. Installable web app with a service worker that caches the static app shell only. It must never cache API responses.
2. Encrypted local store in IndexedDB: a random data key wrapped by a key derived from the user's password and a per-device salt (choose and record PBKDF2 versus Argon2id in DECISIONS.md); AES-GCM per record with a fresh IV and the record type, id and user id as authenticated data; the unwrapped key lives in memory only and is non-extractable. Request persistent storage.
3. Locking: inactivity lock (default 5 minutes, configurable), offline unlock by password with growing delays and local wipe after the configured number of failures, lease enforcement (after the lease, local data is erased and online login is required).
4. Local repository layer: reads from the encrypted cache while offline; writes go to an outbox with a mutation id and client-generated UUIDs; the UI marks pending items.
5. Sync engine: runs on app open, on regaining connection and on a timer; pull then push per the protocol; backoff; resumes after interruption; handles purge instructions, tombstones, wipe instructions and lease responses; only one sync at a time across tabs.
6. UI: status indicator (Online, Offline, Syncing, Pending changes (n), Needs attention, Locked) with last sync time; Sync history screen; Sync issues screen with conflict resolution options; lock screen; secure logout (keep or clear data, clear by default on unregistered devices); clear local data with a warning about unsynced changes; offline-capable approval request create, edit draft and submit; clear warnings that unsynced changes are lost if the password is forgotten or the device is cleared.
7. Nothing sensitive in localStorage, sessionStorage, cookies other than the HttpOnly session cookie, the Cache API or unencrypted IndexedDB.

Tests (Vitest and Playwright with offline mode and separate browser contexts as separate devices): internet disconnection during data entry (including a page reload while offline); reconnection and automatic sync; duplicate prevention when a response is lost and the client retries; two devices editing the same record, conflict shown and resolved; device revoked while offline, wiped on next contact, nothing readable afterwards; encryption at rest (scan every browser storage area for sentinel plaintext and fail if found); inactivity lock discards the key; wrong-password unlock delays and wipe; lease expiry; permission reduced while offline leads to purge on sync; storage-full handling.

Acceptance: I can fill a form with the network off, close and reopen the app, reconnect, and see it synchronise, with the status and history showing what happened.
Report per CLAUDE.md section 9 and stop. State plainly what could not be tested here, for example real iPhone Safari behaviour.
```

---

## Slice 11: Offline approval and financial controls

```
Read CLAUDE.md and docs/HYBRID_ARCHITECTURE.md (section 9). Implement Slice 11.

1. Risk levels: configurable per request type with amount thresholds in TZS. Until the owner supplies real thresholds, any request with an amount is treated as HIGH and the setting is marked unverified. The server sets risk_level; the client cannot.
2. Decisions are online-only: review, approve and reject are refused from the sync endpoint with requires_online in every case. High-risk decisions additionally require fresh online re-authentication (password or two-factor) within a configurable number of minutes.
3. Offline submissions arrive as SUBMITTED (via offline sync), enter the normal workflow, are never auto-approved, and have the approver resolved by the server from the current hierarchy at sync time (any client-chosen approver is ignored). Separation of duties applies. If the approval chain changed while offline, the new chain is used.
4. Reusable "pending-only" offline policy for financial records, which Phase Two financial models must use. Prove it with a test-only model that is not shipped in the product.
5. Quarantine review screen for administrators: list, inspect, accept (applied through the same validation as any push) or discard with a reason; audited. Notify approvers when offline-created requests arrive.

Tests: a forged push containing an approval decision is refused; an offline-created request cannot reach APPROVED without a real online decision by the server-resolved approver; self-approval attempts fail for offline-created requests; changing the hierarchy while a request is queued changes the approver; high-risk decision without recent re-authentication is refused; the pending-only policy test model never becomes final without approval; quarantine accept and discard paths; audit trail for everything.

Acceptance: I can create and submit a request offline, and confirm it cannot bypass the approval hierarchy in any way.
Report per CLAUDE.md section 9 and stop.
```

---

## Slice 12: Full verification and handover

```
Read CLAUDE.md. This slice builds no new features. It verifies and documents Phase One honestly, including the hybrid and offline behaviour.

1. Run the complete test suite (backend, frontend, end-to-end) from a clean database created only from migrations. Record exact commands and results in docs/TEST_REPORT.md. Failures must be listed, not hidden.
2. Explicitly cover each item in CLAUDE.md section 8: account creation, login/logout, password reset, user permissions for every role, department restrictions, approval workflows, audit logging and immutability, mobile responsiveness, database persistence (stop and restart containers, confirm data survives); and every hybrid test in HYBRID_ARCHITECTURE.md section 13 (disconnection during data entry, reconnection and sync, duplicate prevention, conflicting updates, device loss and revocation, encryption at rest, inactivity lock, offline approvals refused, concurrent multi-user sync). Record what could not be tested in the build environment, such as real iPhone and iPad Safari behaviour, and list it as untested rather than passed.
3. Security review pass: check that every API view has a permission class, no secrets are committed, DEBUG is off in production settings, cookies are secure, security headers set, no sensitive data in logs, uploads private, dependencies scanned (pip-audit, npm audit). List findings and fix or flag them.
4. Backup and restore: provide a script for PostgreSQL dumps (including the change log and sync history), document off-site storage, and actually test a restore into a fresh database, then confirm devices resynchronise correctly after the restore.
5. Write docs/ADMIN_SETUP.md: server requirements, environment variables, first admin creation, SMTP setup, creating departments/roles/users, backups and restore, restricted audit DB role setup, device registration and revocation, the lost-or-stolen-device procedure, reviewing quarantined changes and sync conflicts, staff guidance for offline use (install the app, sync often, lock the screen, never share a device), updating the system, and what to do if the main administrator is unavailable (continuity: at least two administrators, credentials held by the institution).
6. Write docs/STATUS.md: every Phase One feature marked Done and tested / Done but untested / Partial / Not done, with no optimism.
7. Confirm there is no personal ownership in the repository (names, emails, accounts), and that the repository owner, domain and hosting recommendations are institutional.

Deliver: summary of completed features, honest list of gaps, test results, setup instructions. Do not begin Phase Two. Stop and wait for my review.
```

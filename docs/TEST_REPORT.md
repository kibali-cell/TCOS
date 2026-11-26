# Test report

Results are recorded as run, including failures and things that could not be run.

## Slice 0

**Environment:** Linux, Python 3.13.18, Node 22.23.5, PostgreSQL 16 (throwaway local cluster, UTF-8), Google Chrome (system install). **No Docker daemon was available.**

### Summary

| Check | Command | Result |
|---|---|---|
| Backend lint | `ruff check .` | Passed |
| Backend format | `ruff format --check .` | Passed (32 files) |
| Frontend lint | `npm run lint` (oxlint) | Passed |
| Type check | `npm run typecheck` (tsc -b) | Passed |
| Pending migrations | `manage.py makemigrations --check --dry-run` | No changes detected |
| Migrate from empty database | new database, `manage.py migrate` | Passed (`contenttypes` 0001, 0002) |
| Backend tests | `pytest` | **12 passed** |
| Frontend unit tests | `npm test` (Vitest) | **17 passed** (3 files) |
| Responsive browser tests | `npx playwright test` | **6 passed** (2 tests x 3 viewports) |
| Production build | `npm run build` | Succeeded |
| Whole pipeline | `make check` | Passed |

### What the tests cover

**Backend (12):** health OK with a live database; health returns 503 with no host or error details in the response or the log when the database fails; JSON-only responses; CSRF cookie set; a view with no permission class is denied; error envelope for validation, not-found and permission errors; production refuses to start without a secret key or allowed hosts; production has DEBUG off, secure cookies, SSL redirect and HSTS; `check --deploy` reports no errors.

**Frontend unit (17):** API client (no CSRF header on GET, token on unsafe methods, token fetched when missing, failure when none can be obtained, error envelope mapping, non-JSON errors, network failures, 204 handling); system status states (loading, ok, 503, unreachable); navigation lists the dashboard and all twelve modules; dashboard contains none of the reference figures; unbuilt module shows "Not yet available"; unknown module shows not found; drawer opens and closes with the button, Escape and link choice.

**Browser (6):** at 360, 768 and 1280 px: permanent sidebar and no menu button on wide screens; hidden navigation, working drawer and Escape-to-close on narrow screens; no horizontal scrolling; navigating to a module shows the notice.

### Manual runtime verification (real processes)

| Scenario | Result |
|---|---|
| Django dev server + real PostgreSQL, `GET /api/v1/health/` | 200 `{"status":"ok","database":"ok"}` |
| Same request through the Vite dev proxy (as the browser does) | 200, same body |
| Frontend page served | Title `TCOS` |
| Database stopped while the server was running | 503 `{"status":"error","database":"unavailable"}` |
| Database restarted | 200 again without restarting the server |
| Server log during outage | One line per probe naming the error type only; no host, port, user or password |
| gunicorn with production settings | Health 200 over plain HTTP (exempt); other paths 301 to HTTPS; `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` present; unlisted `Host` header rejected with 400 |

### Problems found and fixed during testing

1. The e2e spec failed type-checking because the Node tsconfig had no DOM types. Fixed in `tsconfig.node.json`.
2. A formatting difference in `apps/core/api.py`. Fixed with `ruff format`.
3. The health view logged a full traceback on every failed probe, exposing the database host and port in server logs. Changed to log the error type only (D-009) and added a test.
4. Test servers started in one verification step were left running (killing a wrapper subshell does not stop the child). Noticed from an unexpected `Exit 1` notice, cleaned up, and the outage test was re-run cleanly. No stray processes remain.

### Not run, and why

| Item | Reason |
|---|---|
| `docker compose up --build` from a clean checkout | **Update:** the owner later ran it and pasted the logs (database ready, migrations applied, Django started, health check 200, Vite ready), so the Slice 0 criterion is met. Original note: no Docker daemon in the build environment. Only `docker compose config` (syntax and variable validation) was run; it passes, and it correctly refuses to resolve without `POSTGRES_PASSWORD`. **The Slice 0 acceptance criterion "docker compose up brings up all services" is therefore unverified.** |
| Playwright's own Chromium | Download blocked by the environment's network allowlist. Tests ran against the installed Google Chrome instead (D-010). |
| Docker image builds, container health checks | Same Docker limitation |
| Password reset, login, permissions, department restrictions, approvals, audit, persistence across restarts | Not built yet (Slices 1 to 8) |

### Suggested first check on your machine

`docker compose up --build` as described in the README, then open http://localhost:5173 and confirm the Dashboard shows "Server and database are reachable." Please tell me if anything fails; that result belongs in this report.


---

## Slice 1

**Environment:** same as Slice 0 (Linux, Python 3.13, Node 22, PostgreSQL 16 throwaway cluster, system Chrome). No Docker daemon.

### Summary

| Check | Command | Result |
|---|---|---|
| Backend lint and format | `ruff check .`, `ruff format --check .` | Passed (migrations excluded from lint: generated code) |
| Frontend lint, types | `npm run lint`, `npm run typecheck` | Passed, no warnings |
| Pending migrations | `makemigrations --check --dry-run` | No changes detected |
| Migrate from empty database | new database, `manage.py migrate` | Passed (`accounts.0001_initial` applied) |
| Migrate from the Slice 0 database | existing database with `contenttypes` only | Passed; reversible |
| Backend tests | `pytest` | **90 passed** (was 12) |
| Frontend unit tests | `npm test` | **35 passed**, 5 files (was 17) |
| Browser tests | `npx playwright test` | **12 passed** (4 tests x 3 widths) |
| Production build | `npm run build` | Succeeded |
| Whole pipeline | `make check` | Passed |

### What the backend tests cover (78 new)

- **Accounts (28):** creation, name and email normalisation, Argon2id hashes, weak and common passwords, similar-to-username passwords, case-insensitive uniqueness, invalid usernames and phone numbers, database refuses upper-case names and invalid status even if code is bypassed, `is_active` per status, `create_initial_admin` (environment input, password never printed, refuses when users exist, `--force`, password policy applies, no default credentials).
- **Sign in and out (34):** success; HttpOnly SameSite cookie; no secrets in responses; wrong password, unknown user and inactive account give **identical** responses; attempt recording with IP and agent; validation errors; CSRF required on sign-in and on authenticated requests; sign-out deletes the server session and a replayed old cookie is rejected; every protected endpoint rejects anonymous users; signing in again issues a new session key; deactivating an account ends access immediately; lockout after 5 failures blocks even the correct password; the lockout response is identical for unknown usernames; case-insensitive counting; lockout ends after the window; blocked attempts do not extend it; administrator reset; success resets the count; per-IP limit; `X-Forwarded-For` ignored by default and honoured only behind a configured proxy; absolute timeout; idle timeout; last-activity tracking; forced password change blocks ordinary endpoints but not account endpoints.
- **Sessions and password (12):** list shows my devices and marks the current one; no session keys or other users' sessions exposed; ending another session takes effect at once; cannot end my own session that way; cannot end another user's session (404); unknown session 404; **sign out other devices** ends only mine and only others; no-op is harmless; password change ends other sessions and keeps this one; needs the correct current password; policy enforced; new password must differ.
- **Settings and conventions (4 new):** Argon2 first, custom user model, cookie flags.

### What the frontend tests cover (18 new)

Route protection (anonymous redirected and sees no navigation; server unreachable shows retry, not sign-in; forced password change goes to the account page; session ending mid-use returns to sign-in with a notice); sign-in (sends trimmed username and CSRF header, shows server error and clears the password, lockout message, cannot submit empty form); sign-out calls the server; nothing stored in `localStorage` or `sessionStorage`; devices (list and "This device" marking, no sign-out on the current device, sign out one, sign out all others with count, disabled when none, load error); change password (mismatch never reaches the server, server reasons shown beside the field, success clears fields and reports other devices).

**Browser (12):** sign-in page fits 360, 768 and 1280 px with no sideways scrolling and a 44 px touch target; sign in, account page, device list, sign out, and no browser storage; plus the Slice 0 layout checks, now behind a signed-in mock.

### Live check with real processes (no mocks)

Django dev server, real PostgreSQL, real cookies and CSRF, driven with curl:

| Step | Result |
|---|---|
| Anonymous `/me` | 401 |
| Sign in without CSRF token | 403 |
| Sign in as a Windows laptop, then as an iPhone | both 200; session cookie is HttpOnly |
| Session list from the laptop | "Chrome on Windows" (current) and "Safari on iPhone" |
| Sign out other devices from the laptop | `{"ended":1}` |
| iPhone `/me` afterwards | **401** (signed out immediately) |
| Laptop `/me` afterwards | 200 |
| Sign out, then `/me` | 204, then 401 |
| 5 wrong passwords, then the correct password | 401 x5, then **429** |
| Server log | No password or traceback |

One step of my script (change password with a wrong current password) failed because of a quoting error in the script itself (invalid JSON sent), not the server. That case is covered by an automated test (`test_change_password_needs_the_current_password`).

### Problems found and fixed during testing

1. **Real bug:** signing in again while already signed in as the same user kept the same session key (Django's `login()` only rotates it when the user changes). This crashed with a duplicate key error and, more importantly, meant the key was not renewed on sign-in. Found by `test_signing_in_again_replaces_the_previous_session`; fixed (D-028).
2. Three of my own tests had wrong expectations (a field name containing "password", and an example password that is not similar enough to trip the similarity rule); corrected, not the code.
3. Lint: missing `__str__` on two models, one over-long line (the line in generated migration code is excluded from lint).
4. A blanket Prettier run changed the code style of existing files (semicolons, double quotes). I reverted the files I had not meant to touch and reformatted mine to the project style; recorded in D-033.

### Not run, and why

| Item | Reason |
|---|---|
| Docker run with Slice 1 (project name, conditional `npm install`) | No Docker daemon here. Please run the update steps in the README and tell me the result |
| Real iPhone Safari, Android Chrome, Mac Safari, Windows Edge | Only Chrome on Linux available. Layout checked at phone, tablet and desktop widths only |
| Idle and absolute timeouts in real elapsed time | Tested by moving timestamps, not by waiting 30 minutes or 12 hours |
| Production (gunicorn, HTTPS) sign-in, secure cookie in practice | Not repeated for Slice 1. Settings are asserted in tests only |
| Audit events for sign-ins, permissions, user creation in the app | Slices 2, 3, 6 |


---

## Slice 2: roles, permissions, scoped access

**Environment:** as Slice 1 (Linux, Python 3.13, Node 22, PostgreSQL 16 throwaway cluster, system Chrome). No Docker daemon.

### Summary

| Check | Command | Result |
|---|---|---|
| Whole pipeline | `make check` | Passed (exit 0) |
| Backend lint, format | `ruff check .`, `ruff format --check .` | Passed |
| Frontend lint, types | `npm run lint`, `npm run typecheck` | Passed |
| Pending migrations | `makemigrations --check --dry-run` | No changes detected |
| Migrate existing database (Slice 1 data) | `manage.py migrate` | Passed; existing superuser received the Administrator role |
| Seed is repeatable | `manage.py seed_rbac` run again | Created 0 of everything |
| Backend tests | `pytest` | **252 passed** (was 90) |
| Frontend unit tests | `npm test` | **54 passed**, 6 files (was 35) |
| Browser tests | `npx playwright test` | **21 passed** (was 12) |
| Production build | `npm run build` | Succeeded |

### Backend tests by area (162 new)

| File | Tests | Covers |
|---|---|---|
| `test_rbac_engine.py` | 45 | Every scope (ALL, DEPARTMENT, OWN, ASSIGNED) per action; no leakage between modules; users with no roles; anonymous and inactive accounts denied; record grants (one record, one action, one user, expiry, revocation); **union of several roles**; widest scope wins; narrow scopes combine; department-restricted role plus unrestricted role; same role in two departments; role valid dates (both boundary days); revoking or deactivating one role leaves the others; a changed role applies on the next check; `can()` and the list filter agree on every record across 16 scope combinations |
| `test_rbac_seed.py` | 23 | 120 permissions; 11 protected roles; the default matrix for each of the 11 roles; no blanket access; only the Administrator manages users; only the Medical Officer reads medical records; approval needs the assigned scope; seed idempotent and never overwrites edits; migration gives superusers the role; `is_superuser` grants nothing; first-admin command assigns the role |
| `test_rbac_roles_api.py` | 45 | **Each of the 11 roles**: `/auth/me/` reports exactly its permissions; role screens allowed or refused correctly; finance endpoints follow finance permissions; forbidden responses reveal nothing; **a user without access who calls the API directly is refused** (the interface hiding something is not security); anonymous gets 401; forced password change blocks module access; catalogue and role list |
| `test_rbac_management.py` | 27 | Create, rename, delete roles; duplicate names (case-insensitive); built-in roles undeletable; used roles undeletable; matrix replace validates every row and is atomic; **changing a role changes API behaviour immediately** (acceptance criterion); assignments with department and dates; two roles through the API; **nobody can give themselves a role, edit a role they hold, or remove their own roles**; users without Manage Users can change nothing; Administrator role must keep Manage Users; last working Administrator cannot be removed; an expired Administrator does not count |
| `test_rbac_scopes_api.py` | 15 | Through real HTTP: Department A user cannot see Department B records and vice versa; out-of-scope records are 404 not 403; in-department edit and delete; cannot move a record to another department by editing; create limited to own department; user with no department sees nothing; own and assigned scope; the client cannot choose who owns a record; expired role stops mid-session; removing one of two roles leaves the other; record grant opens one record, revocation closes it at once |
| `test_rbac_view_coverage.py` | 7 | Every URL is a DRF view; every view declares its permission policy; RBAC views name their module; the only unauthenticated views are health, CSRF and sign-in; the default permission class is the engine; the guard itself catches a forgotten policy |

### Frontend tests (19 new)

Navigation shows only modules the person may view; roles screen hidden without `users.VIEW`; a person with no roles sees only the dashboard; typing a forbidden module or the roles address shows a refusal and loads nothing; account page lists the person's roles; roles list with holder counts; matrix cells at the right scope; saves exactly the changed cells; removing access sends a smaller matrix; discard; server reason shown when a save is refused; warns before discarding unsaved changes; create role; built-in roles cannot be deleted from the screen and the Administrator cannot be deactivated; delete a custom role after confirmation; deactivation explains the effect; read-only for someone who may view but not manage; load error.

**Browser (9 new, 3 tests x 3 widths):** roles screen shows the whole matrix without sideways scrolling at 360, 768 and 1280 px; navigation shows only permitted modules; a forbidden module address shows a refusal.

### Live check with real processes (no mocks)

Django dev server, real PostgreSQL, real default roles and cookies:

| Step | Result |
|---|---|
| Welfare officer `/me` | Social welfare and child profiles: view, create, edit |
| Welfare officer and Medical officer list roles | **403** (no `users.VIEW`) |
| Administrator lists roles | 200, 11 roles with holder counts |
| Administrator removes "edit child profiles" from the Social Welfare role | 200 |
| Welfare officer `/me` again, **no new sign-in** | child profiles: view, create only (edit gone) |
| Administrator edits his own Administrator role | **403** `self_escalation` |
| Welfare officer tries to edit a role | **403** |
| Anonymous lists roles | 401 |
| Server log | No password, no traceback |

One step (administrator assigns a role to himself) returned 404 because my script failed to look up the user id, so it did not test the rule. That rule is covered by `test_nobody_can_give_themselves_a_role`.

### Problems found and fixed during the slice

1. The first seed attempt failed: I had given approver roles both "own" and "assigned" for the same permission, which the schema's one-scope-per-permission rule rejects. Fixed by making scopes cumulative (D-035) and keeping the widest scope per permission.
2. Lint: two models lacked `__str__`; one over-long line. Fixed.

### Not run, and why

| Item | Reason |
|---|---|
| Docker with Slice 2 | No Docker daemon here. The new migration and seed run on start; please try the update steps |
| Real iPhone, Android, Mac, Edge | Only Chrome on Linux |
| Assigning roles from a screen | Not built: needs the user list (Slice 6). API tested |
| Department creation from a screen | Slice 4. Department scope tested through a test-only model |
| Audit events for role and permission changes | Slice 3 |
| Whether the default grants fit Tuleeni | Needs the owner's review (D-034) |

## Slice 3: audit log

**Environment:** as Slice 2 (Linux, Python 3.13, Node 22, PostgreSQL 16 throwaway cluster, system Chrome). No Docker daemon.

### Summary

| Check | Command | Result |
|---|---|---|
| Whole pipeline | `make check` | Passed (exit 0) |
| Backend lint, format | `ruff check .`, `ruff format --check .` | Passed |
| Frontend lint, types | `npm run lint`, `npm run typecheck` | Passed |
| Pending migrations | `makemigrations --check --dry-run` | No changes detected |
| Migrate an empty database | `manage.py migrate` | Passed; empty chain verifies |
| Migrate the existing development database | `manage.py migrate` | Passed; 11 earlier login attempts carried over, chain intact |
| Backend tests | `pytest` | **380 passed** (was 252) |
| Frontend unit tests | `npm test` | **65 passed**, 7 files (was 54) |
| Browser tests | `npx playwright test` | **30 passed** (was 21) |
| Production build | `npm run build` | Succeeded |

### Backend tests by area (128 new)

| File | Tests | Covers |
|---|---|---|
| `test_audit_core.py` | 42 | Hash chain links and verifies; an edited, deleted or reordered row is detected (with the trigger disabled for the test); the model refuses save-over, delete and bulk methods; **the database refuses UPDATE, DELETE and TRUNCATE as owner and as the restricted role**; the restricted role cannot change `django_migrations`; **the change rolls back if the audit write fails** (create user, create role, set permissions, deactivate, sign in); sanitiser removes secrets at any depth; generic create, update, archive, delete hooks honour excluded fields; backfill of earlier login attempts |
| `test_audit_events.py` | 33 | Exactly one event per action; request id, address and device recorded; sign-in success, failure and block; sign-out and ended sessions; password change (one event, count of ended sessions); user create, edit, no-op writes nothing, deactivate and reactivate; self-deactivation and last-Administrator refused; role create, edit, delete; permission added, removed, rescoped; assign and revoke; **no password, token or hash in any event**; chain valid after a whole workflow; events outlive deleted actors |
| `test_audit_api.py` | 53 | **Each of the 11 roles**: only Administrator and Executive Director may view, nobody may export by default; anonymous 401; refusals reveal nothing; forced password change blocks viewing; no way to create, change or delete events through the API; newest first and paged; summary versus detail; every filter (text, actor, type list, outcome, object, request id, date range inclusive); **day boundaries follow Dar es Salaam time, not UTC**; bad dates and outcome give 400; own and department scope (other records are 404); export needs the export permission, is itself audited once, honours export scope, neutralises spreadsheet formulas, refuses over the limit without recording, ignores unknown filters |

### Frontend tests (11 new)

List with readable event names; refusal for people without audit access and no API request made; only filled-in filters are sent; details show old and new values; paging; empty and error states with the server's reason; export button only with permission, sends the security token, says the export was recorded; too-large export shows the server's reason; helper functions.

**Browser (9 new, 3 tests x 3 widths):** the log is readable at 360, 768 and 1280 px (table on desktop, one card per event on phones), details open, no sideways scrolling, buttons large enough to tap; navigation link and Export button follow permissions; no access shows no log.

### Live check with real processes (no mocks)

Migrations and `setup_database_roles` as the database owner, then the Django server started as the restricted role `tcos_app`:

| Step | Result |
|---|---|
| Health check | 200, database ok |
| Sign in as an Administrator | 200 |
| Create a role | 201 |
| Audit list filtered to role creation | 1 event, by that user |
| Export as Administrator (no export permission by default) | 403 |
| `UPDATE`, `DELETE`, `TRUNCATE` on the audit table as `tcos_app` | All refused: permission denied |
| `UPDATE` on `django_migrations` as `tcos_app` | Refused |
| Ordinary read as `tcos_app` | Works |
| `verify_audit_chain` | Intact, 14 events |
| Server log | No traceback, no password |

### Problems found and fixed during the slice

1. The first audit API test crashed: the permission engine looked up record grants (which hold a UUID) against the audit table's numeric key. The engine now skips record grants for models without a UUID key (D-053). This was a genuine bug that would have hit any numeric-key model.
2. A test expected 405 for writes on the log, but the permission check answers 403 first. Both refuse the request; the test now accepts either and checks nothing was written.
3. Lint and test housekeeping (long lines, a stale test database needing `--create-db`, a test-app migration for an excluded field).

### Not run, and why

| Item | Reason |
|---|---|
| Docker with the restricted database role | No Docker daemon here. The same steps were run by hand against PostgreSQL 16; please try the update steps and add `TCOS_APP_DB_PASSWORD` to `.env` first |
| Real iPhone, Android, Mac, Edge | Only Chrome on Linux |
| Audit of idle-session expiry | Not built (D-051) |
| Export of more than 50,000 events | Refused by design; narrow the filters |

## Slice 4: organisation structure

**Environment:** as Slice 3 (Linux, Python 3.13, Node 22, PostgreSQL 16 throwaway cluster, system Chrome). No Docker daemon.

### Summary

| Check | Command | Result |
|---|---|---|
| Whole pipeline | `make check` | Passed (exit 0) |
| Backend lint, format | `ruff check .`, `ruff format --check .` | Passed |
| Frontend lint, types | `npm run lint`, `npx tsc -b` | Passed |
| Pending migrations | `makemigrations --check --dry-run` | No changes detected |
| Migrate an empty database | `manage.py migrate` | Passed; 12 departments and 12 positions seeded |
| Reverse then re-apply organisation migrations | `migrate organisation 0001`, then `migrate` | Passed both ways |
| Backend tests | `pytest` | **535 passed** (was 380) |
| Frontend unit tests | `npm test` | **88 passed**, 9 files (was 65) |
| Browser tests | `npx playwright test` | **42 passed** (was 30) |
| Production build | `npm run build` | Succeeded |

### Backend tests by area (155 new)

| File | Tests | Covers |
|---|---|---|
| `test_org_models.py` | 25 | Starting structure (12 departments, one head position each, heads report to the Executive Director, no people, flat); re-seeding creates nothing and never undoes edits; every model declares a sync policy with no offline writes; **database refuses**: self-parent, archived-but-active, unstamped archive, duplicate titles, second head position, self-boss, second main assignment, duplicate current position, bad dates, self-reporting, a chain step naming the wrong target for its type, step 0 or a duplicate step |
| `test_org_services.py` | 63 | Create, edit, no-op writes nothing, version rises; **no cycles** for departments, positions and people (including mixed position and override loops) and checks use stored data not stale objects; head rules and clearing when the head leaves; first assignment becomes main and sets the person's department; transfer, make main, end; refusals (inactive, archived, future date, duplicate, second main); **archive blocked** by people, sub-departments, other departments' reporting lines and chains, and later-slice hooks, with counted reasons; archive cascade and restore rules; chains of every kind, replace, empty removes, validation, refused chain keeps the old one; exactly one audit event per change; **a failed audit write undoes the change**; audit chain intact after a workflow; tree shows names only |
| `test_org_api.py` | 66 | **Each of the 11 roles** read, create and archive (Administrator all; Executive Director all but archive; Board Member read only; the other eight nothing); anonymous 401; forced password change blocked; **department-limited grants refused**; CSRF enforced; no hard delete; validation envelope; list search, filters, archived views, paging; blockers shown before archiving; head, position, assignment, transfer, make main flows; reporting loop refused; people search returns names only; **moving a person changes what they can see in the same session**; a second assignment does not widen access; chain round trip and bad chains; options; tree; changes appear in the audit log with the department; a refused change leaves no event; **a department-scoped audit viewer sees only their department's organisation changes**; no email, phone or password in any response |

One Slice 3 test was changed on purpose: `update_user` no longer accepts a department (D-056), so that test now checks the department is refused. The Slice 2 guard test (every view has RBAC) now accepts subclasses of the RBAC permission class.

### Frontend tests (23 new)

Refusal without administration access with no API request made; chart shows nesting, heads, people, vacancies and reporting lines, asks for archived only when told, shows errors; departments list, blockers explained with the Archive button disabled, archive after confirmation, create with a server refusal shown in plain words, edit and name a head, view-only has no write controls; positions create, filter, blockers, cycle refusal shown; staff search, assign by finding a person by name, transfer, end (with cancel and a server refusal), view-only; approval chains load, edit, reorder, save, limit at the maximum, remove, switch request type, server refusal; paging helper including its page limit.

**Browser (12 new, 4 tests x 3 widths):** every section fits 360, 768 and 1280 px with very long department, position and person names and no sideways scrolling; tabs and buttons at least 40 px tall; the Organisation link and screen follow permissions; no access shows no screen.

### Live check with real processes (no mocks)

Migrations and role setup as the owner; Django server started as the restricted role `tcos_app`; real HTTP with CSRF and a session:

| Step | Result |
|---|---|
| Sign in as an Administrator | 200 |
| Tree | 12 seeded departments |
| Create department, position; assign a person | Created |
| Name the person head; set a two-step chain | 200, 200 |
| Archive while that person works there | 400 with "1 person still works in it (move them or end their assignments first)" |
| End assignment (head cleared), then archive | 200, 200 |
| Audit viewer, filtered to organisation | 8 events: created, updated, archived for departments, positions and assignments |
| Person's department after assignment ended | Empty |
| `verify_audit_chain` | Intact, 27 events |
| `DELETE` on the audit log as `tcos_app` | Permission denied |
| Server log | No traceback, no password |

### Problems found and fixed during the slice

1. Cycle and "archived parent" checks followed relations on objects the caller passed in, which can be out of date. They now read stored rows (found by a test that moved a department and then tried to close the loop).
2. The Slice 2 guard test only recognised the exact RBAC class, not the stricter organisation version that also demands institution-wide scope. The guard now accepts subclasses.
3. A person with a department-scoped role and no department gets a refusal (403), not an empty list. The engine was right; the test expectation was wrong.
4. A test assertion on the audit chain used attribute access on a dictionary; test helper tidy-ups; two Vitest queries matched more than one element.
5. A test sequence left the phone menu open over the page; it now closes it as a user would.
6. My first live-check label called a 400 on an archived department a "cycle refusal". It was the archived-department guard; cycles are covered by automated tests.

### Not run, and why

| Item | Reason |
|---|---|
| Docker stack with Slice 4 | No Docker daemon here. The same migrations and server ran outside Docker against PostgreSQL 16 |
| Two people editing the structure at once | One database lock serialises changes, but there is no concurrent-writer test |
| Real iPhone, Android, Mac, Edge | Only Chrome on Linux |
| Approval resolution from chains | Slice 5 |



## Slice 5: Approval Centre

**Environment:** as Slice 4 (Linux, Python 3.13, Node 22, PostgreSQL 16 throwaway cluster, system Chrome). No Docker daemon.

### Summary

| Check | Command | Result |
|---|---|---|
| Whole pipeline | `make check` | Passed (exit 0) |
| Backend tests | `pytest --create-db` | 595 passed (60 new for approvals and sensitive grants) |
| Frontend unit tests | `npx vitest run` | 98 passed (10 new) |
| Browser layout tests | `npx playwright test` | 45 passed (3 new: approvals screens at 360, 768, 1280 px) |
| Pending migrations | `makemigrations --check --dry-run` | No changes detected |
| Migrate an empty database, reverse `approvals` to 0001, apply again | `manage.py migrate` | Passed |

### What the tests cover

Every legal and illegal state change; self-approval through the API; the wrong approver; department limits; escalation when the requester is the only possible approver; two approvers deciding at once; request numbers unique under parallel submission; history refusing change; notifications; sensitive roles refused on the direct route, requester or grantee unable to approve, Administrator grants needing a Board Member, role edits unable to add sensitive access to a role with holders; TZS limits changeable only through an approved request; high-risk decisions needing the password.

### Live check against real PostgreSQL as the restricted role

Fresh database, migrated, `setup_database_roles` run, then connected as `tcos_app`:

| Attempt | Result |
|---|---|
| Insert a history row | Allowed |
| Update, delete, truncate the history | Refused: permission denied |
| Insert an APPROVE row whose actor is the requester | Refused by the trigger |
| Delete history as the database owner | Refused by the trigger |
| Limits in force | Version 1, 200,000 / 2,000,000, not ratified |

### Problems found during the slice

- A stale frontend test clicked Approve before typing the password; the page shows the password box up front. Test corrected, not the page.
- Lint: model methods out of the order the project style requires. Fixed.
- While continuing after a session break I overwrote `approvals/models.py` by mistake and rebuilt it from migration 0001; `makemigrations --check` and all 595 tests confirm it matches.

### Not run, and why

| Not run | Why |
|---|---|
| Docker stack | No Docker daemon available |
| Real devices and browsers other than Chrome on Linux | Not available |
| Multi-user load, and e-mail | No such feature / not configured |
| The approvals flow in a real browser against the real server | Browser tests use mocked API responses; the real server was exercised by backend API tests only |

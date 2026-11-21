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

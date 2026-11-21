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

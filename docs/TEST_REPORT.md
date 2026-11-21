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
| `docker compose up --build` from a clean checkout | No Docker daemon in the build environment. Only `docker compose config` (syntax and variable validation) was run; it passes, and it correctly refuses to resolve without `POSTGRES_PASSWORD`. **The Slice 0 acceptance criterion "docker compose up brings up all services" is therefore unverified.** |
| Playwright's own Chromium | Download blocked by the environment's network allowlist. Tests ran against the installed Google Chrome instead (D-010). |
| Docker image builds, container health checks | Same Docker limitation |
| Password reset, login, permissions, department restrictions, approvals, audit, persistence across restarts | Not built yet (Slices 1 to 8) |

### Suggested first check on your machine

`docker compose up --build` as described in the README, then open http://localhost:5173 and confirm the Dashboard shows "Server and database are reachable." Please tell me if anything fails; that result belongs in this report.

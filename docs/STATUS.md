# Status

Honest completion status. Categories: **Done and tested**, **Done but untested**, **Partial**, **Not done**.

Last updated: Slice 1 built and tested (awaiting review). Hybrid and offline design is documents only.

## Slice 0: Project foundation

| Item | Status | Notes |
|---|---|---|
| Git repository, `.gitignore` (no secrets, uploads, dumps) | Done and tested | Ignore rules checked; `.env` is excluded |
| Repository layout per CLAUDE.md | Done and tested | Seven empty app packages created |
| Django project with base/dev/prod settings | Done and tested | Prod guards tested in a subprocess |
| PostgreSQL connection and migrations | Done and tested | Migrates from an empty database; only `contenttypes` tables exist (see D-003) |
| `/api/v1/health/` | Done and tested | Unit tests plus real server, real database outage and recovery |
| `/api/v1/csrf/` | Done and tested | Sets the CSRF cookie |
| Default-deny permissions and error envelope | Done and tested | Unit tests |
| React app (TypeScript, routing, layout) | Done and tested | 17 unit tests, production build succeeds |
| Responsive navigation (drawer / sidebar) | Done and tested | Real Chrome at 360, 768 and 1280 px |
| CSRF-aware API client | Done and tested | Unit tests |
| Navigation for all 12 modules | Done and tested | Each shows "Not yet available" |
| Linting and formatting (ruff, oxlint, tsc) | Done and tested | `make check` passes |
| Test tooling (pytest, Vitest, Playwright) | Done and tested | |
| Makefile | Done and tested | `make check` run end to end |
| `.env.example`, README | Done but untested | README commands for the non-Docker route follow what was run, but were not replayed verbatim from a clean checkout |
| `docker-compose.yml` and Dockerfiles (Slice 0) | Done; confirmed by owner | The owner ran `docker compose up` and pasted logs: database ready, migrations applied, Django started, health check 200, Vite ready. I could not run Docker myself. The Slice 1 changes to Docker (below) are untested |
| Production build image (static React behind a TLS web server) | **Not done** | Out of scope for Slice 0; the frontend Dockerfile is development-only |
| Backend Dockerfile with production gunicorn | Partial | Gunicorn with prod settings was run outside Docker and works; the image itself is unbuilt |

## Slice 1: Custom user, authentication, sessions, application shell

| Item | Status | Notes |
|---|---|---|
| Custom `User` model before first auth migration | Done and tested | UUID key, lower-case CHECK constraints, status values, derived `is_active`. Migrates from empty and from the Slice 0 database |
| Argon2id password hashing, password policy | Done and tested | 12+ characters, common, numeric and similarity checks |
| Sign in / sign out / `me` | Done and tested | Server-side sessions, HttpOnly cookie, CSRF on every unsafe request including sign-in |
| Failed-attempt recording and lockout | Done and tested | Identical responses for unknown and known users; blocked attempts not counted; IP limit; administrator reset exists in the database but **has no screen until Slice 6** |
| Idle (30 min) and absolute (12 h) timeouts | Done and tested | Unit-tested with manipulated clocks; not waited out in real time |
| Active sessions list, end one session, **sign out other devices** | Done and tested | API tests (including cross-user attempts) and screen tests |
| Change password (ends other sessions) | Done and tested | Forced change for temporary passwords is enforced by the server and the screen |
| `create_initial_admin` command | Done and tested | No default credentials, refuses when users exist |
| Login page, protected routes, account page, session-ended notice | Done and tested | 35 unit tests; real Chrome at 360, 768, 1280 px |
| Real end-to-end check (real Django, PostgreSQL, cookies, CSRF) | Done | curl script, see TEST_REPORT |
| Docker changes (project name, conditional npm install) | **Done but untested** | No Docker daemon here. Please run the update steps in the README |
| Real iPhone, Android and Mac browsers | **Not tested** | Only Chrome on Linux was available. Layout was tested at phone, tablet and desktop widths, not on real devices |
| Login events in the audit log | Not done (Slice 3) | Attempts are recorded in `login_attempt` for now |
| Permissions on `/me` | Not done (Slice 2) | Every signed-in user currently sees all module links |
| Password reset, two-factor authentication | Not done (Slice 7) | An administrator-set password is the only recovery route until then |
| Users cannot yet be created in the application | Not done (Slice 6) | Only the command line can create the first administrator |

## Known limitations

- Roles, permissions, audit, approvals and user management do not exist yet. Any signed-in user sees the same screens.
- Sessions: an idle session expires on the server after 30 minutes but the page only notices on its next request.
- No institutional figures (85 / 42 / 43 / 15 or otherwise) are shown anywhere. The reference-figure mechanism arrives in Slice 6.
- Unknown API URLs return Django's default HTML 404 rather than the JSON error envelope.
- The test database was a throwaway local PostgreSQL 16 cluster, not the Docker `postgres:16` image.

## Phase One slices

| Slice | Status |
|---|---|
| 0 Project setup | Done and reviewed (Docker run confirmed by owner) |
| 1 Custom user, authentication, shell | **Done, awaiting review** |
| 2 Roles, permissions, scoped access | Not started |
| 3 Audit log | Not started |
| 4 Organisation structure | Not started |
| 5 Approval Centre | Not started |
| 6 Dashboard, user management, responsive polish | Not started |
| 7 Password reset, 2FA, document uploads | Not started |
| 8 Device registry, enrolment, revocation | Not started (design written) |
| 9 Synchronisation server | Not started (design written) |
| 10 Offline client (encrypted local store, sync engine, lock) | Not started (design written) |
| 11 Offline approval and financial controls | Not started (design written) |
| 12 Full verification and handover (includes all hybrid tests) | Not started |

## Planning documents

| Document | Status |
|---|---|
| `docs/SCHEMA.md` (now including devices and sync tables) | Draft, awaiting owner review of section 9 |
| `docs/HYBRID_ARCHITECTURE.md` | Design; decisions D-H1 to D-H8 resolved (D-H4 provisional). **Nothing in it is implemented yet** except the sync-ready conventions and session list |
| `docs/PROMPTS.md` | Updated for Slices 0 to 12 |

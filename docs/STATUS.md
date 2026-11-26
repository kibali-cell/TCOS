# Status

Honest completion status. Categories: **Done and tested**, **Done but untested**, **Partial**, **Not done**.

Last updated: Slice 2 built and tested (awaiting review). Hybrid and offline design is documents only.

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

## Slice 2: Roles, permissions, scoped access

| Item | Status | Notes |
|---|---|---|
| Models: permission, role, role permission (with scope), user role (department, dates, revoke), record grant | Done and tested | Constraints in the database: unique rows, valid actions and scopes, date ranges, one live assignment per role and department |
| Seed: 120 permissions, 11 roles, default grants | Done and tested | Data migration plus `manage.py seed_rbac`; idempotent; never overwrites edits |
| Central engine `can()`, queryset filter, DRF permission class | Done and tested | Scopes ALL / DEPARTMENT / OWN / ASSIGNED, cumulative; record grants; union of roles; dates; revoked and inactive roles |
| Every view must declare its policy | Done and tested | A test scans all URLs and fails on a forgotten policy; default class denies a view with no module |
| APIs: catalogue, roles CRUD, matrix replace, assign and revoke roles, department list | Done and tested | Reading needs users.VIEW; changes need users.MANAGE_USERS |
| Protections: no self-escalation, Administrator lock-out guards, built-in roles undeletable | Done and tested | See D-037 |
| `/auth/me/` returns permissions and roles | Done and tested | |
| Navigation and routes filtered by permission | Done and tested | The server remains the authority; direct API calls are tested |
| Roles and permissions screen (matrix, scope selector, create/edit/delete/deactivate) | Done and tested | Read-only for people who may view but not manage users |
| Changing a role's permission changes API behaviour at once | Done and tested | Acceptance criterion; also checked live against a running server |
| **Assigning roles to people from a screen** | **Not done** | The API and its tests exist. The screen needs the user list, which is Slice 6. Until then roles can be assigned through the API or the Django shell |
| **Creating departments** | **Not done** | Slice 4. Department scope is tested with a test-only model |
| Default grants reflect how Tuleeni really works | **Needs your review** | They are my proposal (D-034) |
| Record grants from a screen | Not done | Engine and model are tested; no API or screen yet because no record types exist until Phase Two |
| Audit events for role and permission changes | Done in Slice 3 | See the Slice 3 table |
| Real devices (iPhone, Android, Mac, Edge) | Not tested | Chrome on Linux only |
| Docker with Slice 2 | Not tested | No Docker here. The migration runs on start; please try the update steps |

## Slice 3: Audit log

| Item | Status | Notes |
|---|---|---|
| Append-only audit table with tamper-evident hash chain | Done and tested | App layer, database trigger and restricted role (D-045, D-046, D-048). Tamper detection tested |
| Change and audit event commit together | Done and tested | If the event cannot be written, the change rolls back |
| Sign-ins, failures, blocks, sign-outs, ended sessions, password changes | Done and tested | One event per action |
| User creation, edit, activation, deactivation | Done and tested (services only) | Screens come with Slice 6 |
| Role create, edit, delete, permission changes, assign, revoke | Done and tested | Permission changes list what was added, removed or rescoped |
| Secrets never stored | Done and tested | Sanitiser at any depth; checked across a whole workflow and live |
| Request id, IP address, device on each event | Done and tested | Response carries `X-Request-ID` |
| Viewer API: list, filters, detail, event types | Done and tested | All 11 roles tested; only Administrator and Executive Director can view |
| CSV export | Done and tested | Needs `audit.EXPORT` (nobody has it yet), is itself audited, 50,000 row limit, formula-safe |
| Audit log screen | Done and tested | Filters, details with what changed, paging, cards on phones; checked at 360, 768, 1280 px |
| Earlier login history carried over | Done and tested | Marked `backfilled` |
| Restricted database role in Docker | **Done but untested in Docker** | Verified live against PostgreSQL 16 outside Docker (migrate as owner, serve as `tcos_app`, tamper attempts refused). Needs `TCOS_APP_DB_PASSWORD` in `.env` |
| Idle-session expiry audited | Not done | See D-051 |
| Failed sign-in stores the username as typed | Known limitation | See D-051 |
| Audit events for departments, approvals, documents, devices | Not started | Those features arrive in Slices 4 to 9; each will write events through the same service |
| Real devices (iPhone, Android, Mac, Edge) | Not tested | Chrome on Linux only |

## Known limitations

- Approvals and user management screens do not exist yet. Roles and permissions exist, but no real record types exist yet, so the permissions currently decide only what you see in the navigation and who may manage roles.
- Sessions: an idle session expires on the server after 30 minutes but the page only notices on its next request.
- No institutional figures (85 / 42 / 43 / 15 or otherwise) are shown anywhere. The reference-figure mechanism arrives in Slice 6.
- Unknown API URLs return Django's default HTML 404 rather than the JSON error envelope.
- The test database was a throwaway local PostgreSQL 16 cluster, not the Docker `postgres:16` image.

## Phase One slices

| Slice | Status |
|---|---|
| 0 Project setup | Done and reviewed (Docker run confirmed by owner) |
| 1 Custom user, authentication, shell | Done and reviewed |
| 2 Roles, permissions, scoped access | Done and reviewed |
| 3 Audit log | **Done, awaiting review** |
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

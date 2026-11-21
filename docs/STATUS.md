# Status

Honest completion status. Categories: **Done and tested**, **Done but untested**, **Partial**, **Not done**.

Last updated: Slice 0 complete; hybrid and offline design added (documents only, no code).

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
| `docker-compose.yml` and Dockerfiles | **Done but untested** | Compose file validates (`docker compose config`). **`docker compose up` has not been run**: no Docker daemon was available in the build environment |
| Production build image (static React behind a TLS web server) | **Not done** | Out of scope for Slice 0; the frontend Dockerfile is development-only |
| Backend Dockerfile with production gunicorn | Partial | Gunicorn with prod settings was run outside Docker and works; the image itself is unbuilt |

## Known limitations

- There is no login, user, role, audit or approval functionality yet.
- No institutional figures (85 / 42 / 43 / 15 or otherwise) are shown anywhere. The reference-figure mechanism arrives in Slice 6.
- Unknown API URLs return Django's default HTML 404 rather than the JSON error envelope.
- The test database was a throwaway local PostgreSQL 16 cluster, not the Docker `postgres:16` image.

## Phase One slices

| Slice | Status |
|---|---|
| 0 Project setup | Done, awaiting review (see items above) |
| 1 Custom user, authentication, shell | Not started |
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
| `docs/HYBRID_ARCHITECTURE.md` | Design proposal, awaiting owner decisions D-H1 to D-H8. **Nothing in it is implemented.** |
| `docs/PROMPTS.md` | Updated for Slices 0 to 12 |

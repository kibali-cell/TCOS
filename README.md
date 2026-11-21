# Tuleeni Children Operating System (TCOS)

Institutional management system for **Tuleeni Orphans Home**, Shinga Village, Uru South, Moshi Rural District, Kilimanjaro, Tanzania.

The system, repository, domain, hosting and credentials belong to Tuleeni Orphans Home as an institution.

**Current state:** Phase One, Slice 2 (roles and permissions). You can sign in, manage devices and edit what each role may do on **Administration > Roles and permissions**. Navigation follows each person's permissions. There is no user management screen or institutional data yet. See `docs/STATUS.md` for exactly what exists.

Read `CLAUDE.md` first: it is the standing brief and rule set for everyone working on this project.

## Stack

React + TypeScript (Vite) · Django 5.2 LTS + Django REST Framework · PostgreSQL 16

## Quick start with Docker

Requires Docker with Compose.

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD (generate one with: openssl rand -hex 24)
docker compose up --build
```

Then open:

- Frontend: http://localhost:5173
- Health check: http://localhost:8000/api/v1/health/ (expect `{"status":"ok","database":"ok"}`)

Ports are bound to `127.0.0.1` only. Stop with `docker compose down`. **Never add `-v`** unless you intend to delete the whole database.

### Create the first administrator (once)

With the stack running, in a second terminal:

```bash
docker compose exec backend python manage.py create_initial_admin
```

It asks for a username, email, full name and password (12+ characters). There are no default credentials. The new account receives the Administrator role. Then sign in at http://localhost:5173.

The 11 default roles are created automatically when the database is migrated. To re-run the seed after a future slice adds modules: `docker compose exec backend python manage.py seed_rbac` (it never overwrites roles you have edited).

### Receiving a new slice

Each slice is delivered as an update to the **same** project folder, not a new project:

1. Stop the stack (`docker compose down`, without `-v`).
2. Extract the new zip over your existing folder, replacing files. Keep your `.env`.
3. `docker compose up --build`

Your data lives in a Docker volume, outside the folder, and survives updates. Database migrations run automatically on start. Slice zips never contain `.env` or data.

> Docker run status: the stack was started successfully on the owner's machine for Slice 0 (database ready, migrations applied, health check 200). The Slice 1 run in Docker has not been tested by me; see `docs/TEST_REPORT.md`.

## Quick start without Docker

Requires Python 3.13, Node 22 and a running PostgreSQL 16.

```bash
cp .env.example .env              # set DATABASE_URL to your local database
make setup                        # backend venv + frontend dependencies

cd backend
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver      # terminal 1: http://localhost:8000

cd ../frontend
npm run dev                               # terminal 2: http://localhost:5173
```

## Tests and checks

```bash
make check          # ruff, oxlint, TypeScript, migration check, backend + frontend tests
make test-e2e       # browser tests at 360 / 768 / 1280 px
```

`make check` needs `DATABASE_URL` pointing at a PostgreSQL where the user may create databases (pytest creates and drops its own `test_*` database).

`make test-e2e` uses Playwright's Chromium. If you cannot download it, use an installed Chrome:
`PLAYWRIGHT_CHROME_PATH=/usr/bin/google-chrome make test-e2e`

## Layout

```
backend/    Django project (config/), apps in apps/, tests in tests/
frontend/   React app (src/), unit tests beside the code, browser tests in e2e/
docs/       SCHEMA.md, DECISIONS.md, STATUS.md, TEST_REPORT.md, PROMPTS.md
```

## Development process

Work is delivered in slices, each tested and reviewed before the next begins. The slice prompts are in `docs/PROMPTS.md`.

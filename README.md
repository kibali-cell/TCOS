# Tuleeni Children Operating System (TCOS)

Institutional management system for **Tuleeni Orphans Home**, Shinga Village, Uru South, Moshi Rural District, Kilimanjaro, Tanzania.

The system, repository, domain, hosting and credentials belong to Tuleeni Orphans Home as an institution.

**Current state:** Phase One, Slice 0 (project foundation). There is no login, no user management and no institutional data yet. See `docs/STATUS.md` for exactly what exists.

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

Ports are bound to `127.0.0.1` only. Stop with `docker compose down` (add `-v` only if you want to delete the database volume).

> The Docker stack has been validated for syntax (`docker compose config`) but **has not yet been run end to end**. See `docs/TEST_REPORT.md`.

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
make test-e2e       # responsive browser tests at 360 / 768 / 1280 px
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

# TCOS developer commands. Run `make help`.
# Local (non-Docker) targets expect backend/.venv and DATABASE_URL (see .env.example).

.RECIPEPREFIX = >
PY := backend/.venv/bin/python
RUFF := backend/.venv/bin/ruff

.DEFAULT_GOAL := help
.PHONY: help setup up down logs lint migrations-check test-backend test-frontend test-e2e check

help:
> @echo "make setup             Create backend venv and install backend and frontend dependencies"
> @echo "make up                Start the Docker development stack (needs .env)"
> @echo "make down              Stop the Docker development stack"
> @echo "make logs              Follow Docker logs"
> @echo "make lint              Ruff (lint + format check), oxlint, TypeScript"
> @echo "make migrations-check  Fail if model changes have no migration"
> @echo "make test-backend      Backend tests (needs DATABASE_URL)"
> @echo "make test-frontend     Frontend unit tests"
> @echo "make test-e2e          Responsive browser tests (set PLAYWRIGHT_CHROME_PATH to use system Chrome)"
> @echo "make check             lint + migrations-check + backend and frontend tests"

setup:
> python3 -m venv backend/.venv
> backend/.venv/bin/pip install -r backend/requirements-dev.txt
> cd frontend && npm ci

up:
> docker compose up --build

down:
> docker compose down

logs:
> docker compose logs -f

lint:
> cd backend && ../$(RUFF) check . && ../$(RUFF) format --check .
> cd frontend && npm run lint && npm run typecheck

migrations-check:
> cd backend && ../$(PY) manage.py makemigrations --check --dry-run

test-backend:
> cd backend && ../$(PY) -m pytest

test-frontend:
> cd frontend && npm test

test-e2e:
> cd frontend && npm run test:e2e

check: lint migrations-check test-backend test-frontend

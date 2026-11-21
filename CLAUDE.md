# CLAUDE.md — Tuleeni Children Operating System (TCOS)

Read this file at the start of every session. It is the standing brief for this project.

## 1. Project identity

- **System:** Tuleeni Children Operating System (TCOS), version 1.0
- **Organisation:** Tuleeni Orphans Home
- **Location:** Shinga Village, Uru South, Moshi Rural District, Kilimanjaro, Tanzania
- **Purpose:** A secure, modular, integrated institutional management system covering administration, child welfare, education, medical records, finance, human resources, projects, procurement, stores, donors and reporting.
- **Ownership:** The system, repository, domain, hosting and credentials belong to **Tuleeni Orphans Home as an institution**, never to an individual developer or employee. Do not hard-code personal names, personal emails or personal accounts anywhere in code, configuration, commit metadata templates or documentation.

## 2. Current phase

**PHASE ONE: Foundation and Institutional Administration.**

Phase One now also includes the **hybrid cloud and offline foundation** (Slices 8 to 11, see `docs/HYBRID_ARCHITECTURE.md` and `docs/PROMPTS.md`). Slice 0 is complete. Verification and handover is Slice 12.

Do not start Phase Two work. Do not scaffold later modules beyond empty, clearly marked placeholders in the navigation. Phase Two begins only after Phase One has been tested and reviewed by the owner.

Owner decisions already made: the interface is **English only**; a user **may hold more than one role** (effective permissions are the union, using the widest scope per module and action).

## 3. Stack

- Frontend: React (TypeScript preferred), responsive for phone, tablet and desktop
- Backend: Python, Django, Django REST Framework
- Database: PostgreSQL
- Auth: Django sessions with CSRF protection (server-side, httpOnly cookies). Do not store tokens in localStorage.
- Offline (from Slice 10): installable web app (PWA); service worker caching the static app shell only; IndexedDB for local data; Web Crypto (AES-GCM) for local encryption. No native app in Phase One.
- Tests: pytest + pytest-django for backend; Vitest + React Testing Library for frontend; Playwright for end-to-end, mobile-viewport and offline/multi-device checks
- Deployment target: Docker Compose (Postgres, Django via gunicorn, React static build behind nginx or Caddy)

Use a compatible alternative only if the environment forces it, and record the reason in `docs/DECISIONS.md`.

## 4. Non-negotiable rules

1. **Real operations only.** Every button, form and table must read from or write to the database through the API. No decorative controls, no hard-coded demo data in the UI.
2. **Server-side enforcement.** Authentication and permissions are enforced in the API. Hiding a button in the UI is never security.
3. **Do not mark incomplete work as complete.** In status reports, separate clearly: Done and tested / Done but untested / Partial / Not started. Be honest about gaps.
4. **Preserve existing work.** Before changing anything in a non-empty area, inspect it. Never destroy data. Migrations must be reversible where practical and must never drop data silently.
5. **Audit everything that matters.** Every state-changing action writes an audit event (see section 7). Audit records are append-only.
6. **Separation of duties.** A user can never approve, reject or review their own request, regardless of role.
7. **Sensitive child data** is never placed in public or static files, URLs, logs, error messages, fixtures or test snapshots. Uploaded files live in private storage and are served only through authenticated, permission-checked endpoints.
8. **Reference figures are not live data.** The figures 85 children, 42 residential, 43 outreach and 15 employees are initial reference configuration only. Store them as clearly labelled reference figures with `is_verified = false`. The dashboard shows real database counts once records exist and labels any figure that is still a reference figure.
9. **No secrets in the repository.** Use environment variables. Provide `.env.example` only.
10. **Stop at review gates.** After each slice, run tests, report honestly, and wait for the owner's go-ahead before starting the next slice.

### Hybrid and offline rules (details in `docs/HYBRID_ARCHITECTURE.md`)

11. **One central database is the only source of truth.** The server decides permissions, approvers, request numbers, status and validity. Never trust client-supplied authority, timestamps for ordering, or approver choices.
12. **Sync-ready from Slice 1.** Synced models use client-generated UUIDs, an integer `version`, `updated_at`/`updated_by`, archival instead of deletion, and are changed only through service functions that can write the change log.
13. **Nothing sensitive in unprotected browser storage.** No data, tokens or personal information in localStorage, sessionStorage, the service-worker cache, or unencrypted IndexedDB. The service worker never caches API responses. Local data is encrypted with keys that exist unwrapped only in memory.
14. **Offline never bypasses controls.** Approve, reject and review decisions are online-only. Offline-created requests and financial transactions arrive as pending and enter the normal approval hierarchy, resolved by the server at sync time. Permissions are re-checked at sync time.
15. **No silent overwrites, no duplicates.** Every queued change has a mutation id and is applied idempotently. Conflicts are recorded and resolved explicitly, never by last-write-wins on approvals or financial records.
16. **Every model declares a sync policy.** A model with no sync policy is online-only. `CHILD_SENSITIVE` data is not cached on devices unless the owner explicitly decides otherwise (D-H1).

## 5. Architecture conventions

### Repository layout

```
tcos/
  CLAUDE.md
  README.md
  docker-compose.yml
  .env.example
  docs/
    DECISIONS.md          # architecture decisions and reasons
    SCHEMA.md             # database design (source of truth for review)
    HYBRID_ARCHITECTURE.md # cloud + offline design, threat model, test plan
    PROMPTS.md            # staged build prompts
    ADMIN_SETUP.md        # administrator setup instructions
    TEST_REPORT.md        # test results per slice
    STATUS.md             # honest completion status per feature
  backend/
    manage.py
    config/               # settings (base, dev, prod), urls, wsgi/asgi
    apps/
      core/               # base models, sequences, notifications, documents, settings
      accounts/           # custom User, auth, 2FA, password reset
      rbac/               # roles, permissions, scopes, record grants
      organisation/       # departments, positions, assignments, hierarchies
      approvals/          # workflows, requests, actions
      audit/              # append-only audit log
      dashboard/          # aggregation endpoints
      devices/            # device registry, enrolment, revocation, leases (Slice 8)
      sync/               # change log, pull/push, conflicts, history (Slice 9)
      # Phase Two+ apps are NOT created yet
  frontend/
    src/
      app/                # routing, layout, providers
      features/           # one folder per feature area
      components/         # shared UI
      lib/                # API client, auth, permission helpers
      offline/            # encrypted local store, outbox, sync engine, lock (Slice 10)
```

### Backend

- Custom `User` model defined **before the first migration**. Never use Django's built-in `User`.
- UUID primary keys for all domain tables. Use `created_at`, `updated_at`, `created_by` where relevant.
- Business logic lives in `services.py` per app, not in views or serializers. Views are thin.
- Permission checks go through a single central function/class (`rbac.permissions`), used by every DRF view. No ad hoc `if user.role == ...` checks.
- Prefer archival (`is_archived`, `archived_at`, `archived_by`) over hard deletion. Hard deletion of anything sensitive requires an explicit permission and an audit event.
- Every list endpoint supports pagination, search and filtering.
- API versioned under `/api/v1/`. Consistent error format.
- Database constraints (unique, check, foreign keys, indexes) are defined in models and migrations, not only in validation code.

### Frontend

- Mobile-first. Test at 360px, 768px and 1280px widths.
- Sidebar on desktop; collapsible drawer or bottom navigation on mobile.
- Navigation items and actions are shown according to the permissions returned by `/api/v1/auth/me/`, but the server remains the authority.
- Clear loading, empty and error states. Accessible forms (labels, keyboard use, contrast).
- Printable reports use a dedicated print stylesheet. No sensitive data in page titles or URLs.

## 6. Roles and permissions (summary)

Roles (configurable, not hard-coded): Board Member, Executive Director, Administrator, Social Welfare Officer, Education Officer, Medical Officer, Finance Officer, Project Manager, Storekeeper, Procurement Officer, HR Officer.

Permission actions: `VIEW`, `CREATE`, `EDIT`, `DELETE`, `APPROVE`, `REJECT`, `EXPORT`, `MANAGE_USERS`.

A user may hold **several roles**. Effective permission is the union of all active roles, using the widest scope per (module, action). A permission is a (module, action) pair. Each role grant carries a **scope**: `ALL`, `DEPARTMENT`, `OWN`, or `ASSIGNED`. Record-specific access is granted through explicit record grants. Permissions are assigned independently per role and can be adjusted by authorised administrators. Full design: `docs/SCHEMA.md`.

## 7. Audit and security requirements

Record, at minimum: successful logins, failed login attempts, user account changes, permission changes, record creation, record modification, approval decisions, data exports, deletion/archival.

- Audit table is append-only: enforced in the application **and** at the database level (revoked UPDATE/DELETE for the application role, plus a trigger that raises on UPDATE/DELETE).
- Each event stores actor, timestamp, event type, object reference, before/after changes (excluding secrets and sensitive child fields), IP address, user agent and request id.
- Passwords: Django's PBKDF2/Argon2 hashers, minimum length and common-password validation, lockout after repeated failures, generic error messages on login and password reset (no account enumeration).
- Optional TOTP two-factor authentication, with hashed recovery codes.
- Rate limiting on login and password reset. Secure cookie flags, HTTPS-only in production, security headers.

## 8. Testing expectations

Phase One is not complete until these are tested and results are written to `docs/TEST_REPORT.md`:

account creation, login/logout, password reset, user permissions (every role, including negative tests, and users holding several roles), department restrictions, approval workflows (including self-approval prevention), audit logging (including immutability), mobile responsiveness, database persistence (data survives restart).

Hybrid and offline (see `docs/HYBRID_ARCHITECTURE.md` section 13): internet disconnection during data entry, reconnection and synchronisation, duplicate prevention, conflicting record updates, device loss and access revocation, encryption at rest (no plaintext in any browser storage), inactivity lock, offline approvals refused, concurrent multi-user sync.

Run before every report: backend tests, frontend tests, linters, `makemigrations --check`, and the migration from an empty database.

## 9. How to report after each slice

Provide:
1. What was built (files, endpoints, screens).
2. Test results (commands run and actual output summary).
3. What is **not** done or only partial.
4. Decisions made and anything that needs the owner's input.
5. Update `docs/STATUS.md` accordingly.

Then stop and wait for review.

## 10. Final Phase One deliverable

A functional application; database migrations; test results (`docs/TEST_REPORT.md`); administrator setup instructions (`docs/ADMIN_SETUP.md`); a summary of completed features (`docs/STATUS.md`). Incomplete functionality must be listed as incomplete.

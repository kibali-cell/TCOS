# Decisions

Living record of architecture and process decisions. Newest at the bottom.

## Slice 0

### D-001 Django 5.2 LTS
Chosen for long-term security support, which suits an institutional system that will be maintained for years by a small team. Pinned in `backend/requirements.txt`.

### D-002 oxlint instead of ESLint
The Vite React-TypeScript template ships with `oxlint` and TypeScript 7. ESLint with typescript-eslint was not adopted to avoid compatibility risk with the new TypeScript. `npm run lint` runs oxlint; `npm run typecheck` runs the TypeScript compiler. Revisit if a rule we need is missing.

### D-003 Auth, sessions and admin are NOT installed in Slice 0
`django.contrib.auth`, `sessions` and `admin` are deliberately absent from `INSTALLED_APPS`. Changing `AUTH_USER_MODEL` after the first auth migration has been applied is painful and error-prone, so Slice 1 installs them together with the custom `User` model. As a result, Slice 0 migrations only create the `contenttypes` tables.

### D-004 Deny by default
`REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` is `apps.core.permissions.DenyByDefault`. A view that forgets to declare permissions returns 403 instead of exposing data. Public views (health, CSRF) declare `AllowAny` explicitly. Slice 2 replaces the default with the central RBAC engine.

### D-005 JSON-only API, consistent error envelope
No browsable API in any environment. All errors use `{"error": {"code", "message", "details"}}`. `details` is populated only for validation errors.

### D-006 CSRF cookie is readable by JavaScript
`CSRF_COOKIE_HTTPONLY = False` so the single-page app can send the token in the `X-CSRFToken` header (standard Django pattern for SPAs). The session cookie added in Slice 1 will be HttpOnly. No tokens are stored in `localStorage`.

### D-007 Same-origin API through a proxy
The browser talks to one origin. In development Vite proxies `/api` to Django; in production the web server will do the same. This avoids CORS entirely and keeps cookies same-origin.

### D-008 Production settings fail closed
`config.settings.prod` refuses to start without a 50+ character `DJANGO_SECRET_KEY` and a non-empty `DJANGO_ALLOWED_HOSTS`. `wsgi.py` and `asgi.py` default to production settings so a misconfigured deployment cannot silently run with development settings. HTTPS redirect is on by default, with only the health endpoint exempt so container health checks work over the private network.

### D-009 Health endpoint logs the error type only
Failed probes log `OperationalError`-style type names, not tracebacks, because tracebacks include database host, port and user and probes run every few seconds. Verified in tests and against a real database outage.

### D-010 Browser tests may use an installed Chrome
Playwright's Chromium download was blocked in the build environment. `playwright.config.ts` accepts `PLAYWRIGHT_CHROME_PATH` to use an installed Chrome. The default (no variable set) is Playwright's own Chromium, unchanged.

### D-011 Neutral commit identity
The repository uses the placeholder identity `TCOS Development <tcos-dev@example.invalid>`, not a personal name or email. Replace with Tuleeni's institutional identity when the repository is created under the organisation's account. Commits made with AI assistance carry a `Co-Authored-By` trailer for transparency; these can be dropped if the institution prefers.

## Owner decisions and hybrid architecture

### D-012 English only (owner decision)
The interface is English only. No translation framework is needed. Dates and times display in Africa/Dar_es_Salaam; currency is TZS.

### D-013 Users may hold several roles (owner decision)
A user may hold more than one role. Effective permission is the union of all active roles, using the widest scope per (module, action). Slice 2 tests must cover multi-role users, including a role limited to one department combined with a broader role.

### D-014 Hybrid cloud and offline architecture adopted as a design (pending detail confirmation)
TCOS is a hybrid system: one central cloud PostgreSQL database, with an installable web app (PWA) that works through internet interruptions using encrypted local storage and later synchronisation. Full design, threat model and test plan: `docs/HYBRID_ARCHITECTURE.md`. A native app is not planned for Phase One. **Design only: nothing is implemented yet.** Implementation is Slices 8 to 11.

### D-015 Sync-ready conventions apply from Slice 1
Offline support cannot be bolted on at the end without rework. Synced models use client-generated UUIDs, a `version` column, `updated_at`/`updated_by`, archival instead of deletion, and service-layer writes that can append to the change log (CLAUDE.md rule 12).

### D-016 Approval decisions are online-only (proposed, stricter than the requirement)
The requirement says high-risk approvals must be verified online. The proposed rule is that **all** approve, reject and review actions are online-only, because it is simpler to reason about and cannot be bypassed. The owner may relax it for low-risk request types (D-H3).

### D-017 Slice renumbering
New slices: 8 device registry, 9 sync server, 10 offline client, 11 offline approval and financial controls. Full verification and handover moves from Slice 8 to Slice 12 and now includes all hybrid tests.

### D-018 Document uploads are online-only in Phase One
Offline file handling multiplies the encrypted-storage and quota problems. Offline submissions needing a document are completed online.

## Pending owner decisions

Still open in `docs/SCHEMA.md` section 9: scope semantics for sensitive modules, approval hierarchy tables, single versus multi-step approvals, audit hash chain, requester-as-only-approver policy, default permission grants, session management, data protection review and hosting region (now firm, because the database is in the cloud).

Hybrid decisions D-H1 to D-H8 in `docs/HYBRID_ARCHITECTURE.md` section 14, each with a proposed default: child-sensitive records on devices, offline lease length, offline decisions, TZS risk thresholds, inactivity lock time, device types in use, who manages devices, quarantine policy.

Needed before: Slice 1 (session management), Slice 2 (scope semantics, default grants), Slice 3 (hash chain), Slice 5 (approval chains, requester policy), Slice 8 (D-H2, D-H6, D-H7, D-H8), Slice 10 (D-H1, D-H5), Slice 11 (D-H3, D-H4), and before deployment (hosting region, data protection review).

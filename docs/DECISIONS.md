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

## Hybrid decisions resolved (2026-11-20)

The values are in `docs/HYBRID_ARCHITECTURE.md` section 14. Summary:

### D-019 Offline policy decisions
No `CHILD_SENSITIVE` data cached on devices (D-H1); 7-day offline lease (D-H2); approval decisions online-only for every request type (D-H3). All three are the owner's acceptance of the proposals.

### D-020 Provisional TZS risk tiers (D-H4, builder's proposal)
LOW up to TZS 200,000; MEDIUM 200,001 to 2,000,000; HIGH above 2,000,000; payroll, staff loans, bank or payee changes, asset disposal and write-offs, and donor refunds are always HIGH. These were chosen without knowing the home's real spending pattern. They are configuration, and **must be ratified by the Board or Executive Director** before Slice 11 is signed off.

### D-021 Devices in use (D-H5, owner)
Windows and Mac computers, Android phones and iPhones. iOS storage limits and the lack of background sync are documented in the hybrid design. Real-iPhone testing is required and has not been done.

### D-022 Device management and lock policy (D-H6 to D-H8, builder's decision)
Lock after 5 minutes of inactivity on devices holding offline data. Administrator registers devices; Administrator and Executive Director revoke; users may suspend their own devices. Changes from a revoked device are quarantined, reviewed by someone other than the device's user, and never auto-applied.

### D-023 "Sign out other devices" is a Phase One feature (owner)
Built in Slice 1 on the account page.

## Slice 1

### D-024 Lower-case CHECK constraints instead of `citext`
Usernames and emails are normalised to lower case in code and the database enforces it with `CHECK (col = lower(col))` plus unique constraints. This avoids depending on a PostgreSQL extension and gives case-insensitive uniqueness that holds even if code is bypassed (tested).

### D-025 `is_active` is derived, not stored
`is_active` is a property of `status == ACTIVE`. One source of truth means an account can never be "ACTIVE" and "inactive" at once.

### D-026 Lockout is derived from `login_attempt`
5 failed attempts for a username within 15 minutes blocks that username; 30 failures per IP address blocks the address. Blocked attempts are recorded but **not counted**, so an attacker cannot keep someone locked out forever by hammering the form. The unknown-user and known-user responses are byte-identical, so the form does not reveal which usernames exist. A successful sign-in or an administrator reset (`lockout_reset_at`) clears the count. `X-Forwarded-For` is ignored unless `TCOS_TRUSTED_PROXY_COUNT` is set (production behind a proxy), otherwise the client could pick its own IP.

### D-027 Session timeouts and server-side revocation
Idle timeout 30 minutes, absolute timeout 12 hours, both enforced by the server. Sessions are database-backed and mirrored in `user_session`, so any session can be ended instantly and the old cookie then stops working (tested by replaying a stolen cookie). Changing the password ends all other sessions. This idle timeout is separate from the 5-minute offline lock in D-022.

### D-028 A new sign-in always rotates the session key
Found by a test: Django's `login()` keeps the same key when the same user signs in again while already signed in. Slice 1 always starts a fresh session, which also prevents session fixation.

### D-029 `session_key` stored in plain text in `user_session`
It is the same value already held in `django_session`, so storing it adds no exposure, and it is needed to end a session. It is never returned by the API. Slice 8 may revisit this when devices are linked.

### D-030 First administrator is a superuser until Slice 2
`create_initial_admin` sets `is_superuser` because the Administrator role does not exist yet. Slice 2 replaces this with the role and keeps `is_superuser` for emergency break-glass only. The command refuses to run once users exist unless `--force` is given, and has no default credentials.

### D-031 Department and position links deferred
`user.department_id` and `position_id` arrive in Slice 4 with their tables.

### D-032 Docker per-slice updates
Compose project name pinned to `tcos` so the database volume is never orphaned by renaming the folder. The frontend reinstalls packages only when `package-lock.json` changes (`npm install`, not `npm ci`, because `npm ci` cannot delete a Docker volume mount). **Not yet tested in Docker.**

### D-033 Prettier style file
`frontend/.prettierrc.json` records the existing code style (no semicolons, single quotes, 100 columns). Prettier is not a project dependency yet; the file only prevents accidental restyling by someone who runs it.

## Pending owner decisions

Still open in `docs/SCHEMA.md` section 9: scope semantics for sensitive modules (needed before Slice 2), approval hierarchy tables, single versus multi-step approvals, audit hash chain, requester-as-only-approver policy, default permission grants, data protection review and hosting region (firm, because the database is in the cloud).

Also: ratify the TZS tiers (D-020) before Slice 11, and confirm the builder's choices in D-022.

Needed before: Slice 2 (scope semantics, default grants), Slice 3 (hash chain), Slice 5 (approval chains, requester policy), Slice 11 (TZS ratification), and before deployment (hosting region, data protection review).

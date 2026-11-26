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

### D-030 First administrator: superuser flag replaced by the role (done in Slice 2)
Slice 1 set `is_superuser` because no roles existed. From Slice 2 `create_initial_admin` assigns the **Administrator role** and no longer sets the flag. The flag is kept on the table but **grants nothing**; the engine ignores it. The Slice 2 migration gives the Administrator role to any existing superuser. The command still refuses to run once users exist unless `--force` is given, and has no default credentials.

### D-031 Department and position links (department pulled forward to Slice 2)
Department-scoped access cannot be built or tested without a department, so Slice 2 adds a **minimal** `Department` (id, code, name, is_active) and `user.department` (primary department). Slice 4 adds hierarchy, heads, positions and staff assignments on top. `position_id` stays in Slice 4. No departments are seeded (no invented data); until Slice 4 they can only be created from the Django shell.

### D-032 Docker per-slice updates
Compose project name pinned to `tcos` so the database volume is never orphaned by renaming the folder. The frontend reinstalls packages only when `package-lock.json` changes (`npm install`, not `npm ci`, because `npm ci` cannot delete a Docker volume mount). **Not yet tested in Docker.**

### D-033 Prettier style file
`frontend/.prettierrc.json` records the existing code style (no semicolons, single quotes, 100 columns). Prettier is not a project dependency yet; the file only prevents accidental restyling by someone who runs it.

## Slice 2: roles, permissions and scoped access

### D-034 Default grants per role (PLEASE REVIEW AND CORRECT)

These are my proposal, not facts about how Tuleeni works. Every cell is editable on the **Roles and permissions** screen, and tests lock the defaults (`test_default_grants_match_the_reviewed_matrix`). Letters: **V** view, **C** create, **E** edit, **D** delete, **A** approve, **R** reject, **X** export, **M** manage users. Scope in brackets: *all*, *dept* (department), *own* (created by me), *assigned* (assigned to me).

| Role | Default grants |
|---|---|
| Board Member | Institutional Administration: V (all); Financial Management: V (all); Project Management: V (all); Donor Management: V (all); Reports and Analytics: VX (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Executive Director | Institutional Administration: VCE (all); Social Welfare Management: V (all); Child Profile Management: V (all); Education Management: V (all); Financial Management: VX (all); Project Management: V (all); Human Resources: V (all); Procurement: V (all); Stores and Inventory: V (all); Donor Management: V (all); Reports and Analytics: VX (all); Approval Centre: V (all); Approval Centre: AR (assigned); Approval Centre: C (own); Audit Log: V (all); Users, Roles and Permissions: V (all) |
| Administrator | Institutional Administration: VCED (all); Approval Centre: V (all); Audit Log: V (all); Users, Roles and Permissions: VCEDM (all) |
| Social Welfare Officer | Social Welfare Management: VCE (all); Child Profile Management: VCE (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Education Officer | Child Profile Management: V (all); Education Management: VCE (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Medical Officer | Child Profile Management: V (all); Medical Management: VCE (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Finance Officer | Financial Management: VCEX (all); Procurement: V (all); Donor Management: V (all); Reports and Analytics: VX (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Project Manager | Financial Management: V (dept); Project Management: VCE (all); Donor Management: V (all); Reports and Analytics: V (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| Storekeeper | Procurement: V (all); Stores and Inventory: VCE (all); Approval Centre: VC (own) |
| Procurement Officer | Procurement: VCE (all); Stores and Inventory: V (all); Approval Centre: VAR (assigned); Approval Centre: C (own) |
| HR Officer | Human Resources: VCEX (all); Approval Centre: VAR (assigned); Approval Centre: C (own); Users, Roles and Permissions: V (all) |

Principles behind them:
- **No blanket access.** The Administrator is broad only over system modules (users, administration, audit) and cannot see welfare, medical or financial records or approve anything.
- **Medical records are read only by the Medical Officer.** Even the Executive Director has no medical access by default. Child profiles can be read by the roles that need them.
- **Anyone may raise and see their own requests** (Approval Centre: create and view, own). Roles that head a function may decide requests *assigned* to them. Who is assigned is decided by the approval chain in Slice 5, and a person can never decide their own request.
- **Finance Officer, not the Administrator, handles money.** Project Manager sees finance only for their own department.

Questions for you: Should the Executive Director see medical records? Should the Administrator see the audit log (it can only view it)? Should the Board see child profiles or only reports? Who besides Finance may export?

### D-035 Scopes are cumulative
ALL covers everything; DEPARTMENT covers the user's department plus anything assigned to or created by them; ASSIGNED covers assigned plus own; OWN covers what the user created or is the subject of. A role has **one** scope per permission (the schema's unique row), so cumulative scopes let an approver have "assigned" and still see their own requests. A department-limited role assignment confines every grant of that role, even an ALL grant, to that department. Several roles combine by union.

### D-036 Out-of-scope records answer 404, not 403
A person who may not see a record cannot tell whether it exists. Listing and fetching are filtered by the same engine function, and a test checks that the filter and the single-record check agree for every scope.

### D-037 No self-escalation, and lock-out guards
Nobody can assign a role to themselves, change or remove their own assignments, or change the permissions, name, status or existence of a role they currently hold. The Administrator role must always keep "Manage Users on Users (All)", cannot be deactivated or deleted, and its last working holder cannot be removed. Built-in roles cannot be deleted; a role that was ever assigned cannot be deleted (deactivate it).

**Known limit, not solved here:** two administrators acting together can still hand out powerful roles to each other's chosen people. Slice 3's audit log makes it visible. Whether granting sensitive roles should need a second person's approval through the Approval Centre (Slice 5) is for you to decide.

### D-038 Role changes apply on the very next request
Nothing about permissions is cached across requests. Access is computed once per request. Removing a role, expiring one or editing a matrix is effective immediately for everyone, including people already signed in (verified live: a signed-in user lost an action without signing in again).

### D-039 Revoking keeps history
Removing a role from a person sets `revoked_at` and keeps the row. Uniqueness applies only to live assignments, so a role can be granted again later.

### D-040 `is_superuser` grants nothing
No hidden super-powers. Access comes only from roles and record grants.

### D-041 Seeding is safe to repeat
Permissions, the 11 roles and their default grants are created by a data migration and by `manage.py seed_rbac`. Re-running creates only what is missing and never overwrites a role you have edited. Adding a module later means adding it to `apps/rbac/constants.py` and re-running the command.

### D-042 A test fails if a view forgets its permissions
`test_rbac_view_coverage` scans every URL. Each must be a DRF view that declares a permission policy; RBAC views must name their module; the only open views are the allow-listed ones (health, CSRF, sign-in). The default permission class is the central engine, which denies any view with no module.

### D-043 Test-only models
Department, own and assigned scope tests use a small test-only app (`tests/rbac_testapp`, `tests/settings_test.py`) because no real record types exist until Phase Two. It is never installed in the real settings.

## Slice 3: audit log

### D-044 Sensitive role grants go through the Approval Centre (owner decision)
Granting a sensitive role will need a second person's approval, handled by the Approval Centre. Decided by the owner ("Yes, use the Approval Centre"). It is built in Slice 5, when the Approval Centre exists. Until then role assignment stays direct, with the self-escalation guards from D-037, and every assignment is audited.

### D-045 The audit log cannot be changed, in three layers
1. The application: the model refuses to save over an existing row, delete, or use the bulk queryset methods; rows are only added through `audit.service.record`.
2. The database: a trigger raises on UPDATE and DELETE (per row) and on TRUNCATE, for every role including the owner.
3. The restricted database role the server runs as has only SELECT and INSERT on the audit table (D-048).

### D-046 Tamper-evident hash chain is included (closes SCHEMA 9.5)
Each event stores the hash of the one before it and its own hash over its content. `manage.py verify_audit_chain` and `audit.service.verify_chain()` detect an edited, removed or reordered event. A write lock serialises inserts so the chain has one order. Limit, stated plainly: someone with full database superuser access could rewrite the whole chain consistently. The defence is to keep the head hash (printed by the command) somewhere off the server, for example in the monthly report to the board.

### D-047 The change and its audit event commit together
Every audited action runs in one transaction with its audit event. If the event cannot be written, the change is rolled back. The system never records a change without its evidence, and never loses the evidence of a change.

### D-048 The server runs as a restricted database role
Migrations and `setup_database_roles` run as the owner. The running server uses `tcos_app`, which cannot update, delete or truncate the audit log, and cannot change `django_migrations`. This needs one new value in `.env`: `TCOS_APP_DB_PASSWORD`. Docker Compose handles the two connections; `docs/ADMIN_SETUP.md` explains it.

### D-049 What is recorded, and what never is
Recorded: sign-ins (success, failure, blocked), sign-outs, ended sessions, password changes, user creation, edits and (de)activation, role creation, edits and deletion, every permission change (added, removed, scope changed), role assignment and removal, and exports of the audit log. A sanitiser removes anything that looks secret (passwords, tokens, session keys, hashes, one-time codes) at any depth before it is stored. Models can exclude further fields with `AUDIT_EXCLUDE_FIELDS`, which is how child-sensitive fields will be kept out later.

### D-050 Who can see the log, and export
Only the Administrator and the Executive Director can view it (nobody else gets it by default). Nobody can export by default; an administrator must give `audit.EXPORT` to a role on purpose. Exports are CSV, limited to 50,000 rows (narrow the filters otherwise), recorded in the log before the data leaves, and cells that start with a spreadsheet formula character are neutralised. A person limited to "own" scope sees only events they performed; "department" scope sees that department's events.

### D-051 Two honest limits in what is recorded
An idle session that expires on its own is not audited (the server notices only on the next request). A failed sign-in records the username as typed, shortened to 150 characters; a mistyped password in the username box would therefore appear in the log. Both are small and are listed in STATUS.

### D-052 Earlier sign-in history was carried over
Existing login attempts were copied into the audit log once, marked `backfilled`, so the chain does not start empty.

### D-053 Record grants only apply to models with UUID keys
Record grants store a UUID, so a model with another kind of key (the audit table uses a number) cannot be the target of one. The engine skips record grants for such models instead of failing. Found by the first audit API test.

### D-054 New user services wait for their screen
`update_user` and `set_user_status` (with the protections: no self-deactivation, never the last working Administrator, sessions end when someone is deactivated) are built and audited now, with tests. Their screens arrive with user management in Slice 6.

## Slice 4: organisation structure

### D-055 Starting structure (PROPOSAL, please review)
One department for each of the twelve modules, each with a head position, plus an Executive Director position (in Institutional Administration) that the other heads report to: Institutional Administration, Social Welfare, Child Profiles, Education, Medical, Finance, Projects, Human Resources, Procurement, Stores and Inventory, Donor Relations, Reports and Analytics. All are top-level (no nesting) and no people are created. Everything can be renamed, nested or archived from the Organisation screen. The seed only creates what is missing and never undoes later edits. It runs inside a migration, so it is not itself in the audit log.

### D-056 A person's department is their main staff assignment
`user.department` is what department-scoped access reads. It now always follows the person's *main* current assignment, and `update_user` no longer accepts a department. Moving someone changes what they can see at once, in their existing session, with no sign-in needed. A person with no main assignment has no department, so a department-scoped grant gives them nothing until they are assigned. `create_user` still accepts a department for test fixtures; the Slice 6 screen will use assignments.

### D-057 Assignments take effect immediately
An assignment is current while it has no end date. There are no future-dated starts or ends. Transfer ends the old assignment and starts the new one in one step; history is kept. A first assignment becomes the main one. A second main one is refused (use Transfer, or add it as additional). "Make main" demotes the old one to additional. Ending the main assignment leaves the person with no department; nothing is promoted automatically.

### D-058 Who may change the structure
The `administration` module, at institution-wide (ALL) scope only: VIEW to read, CREATE to add, EDIT to change, assign and edit chains, DELETE to archive. By default that means the Administrator can do everything, the Executive Director can do everything except archive, and the Board Member can only look. A department-limited grant is not enough.

### D-059 Archiving rules
Nothing is ever deleted. A department cannot be archived while people work in it, it has active sub-departments, or positions or approval steps in other departments depend on it; a position cannot be archived while someone holds it, others report to it, or a chain names it. The screen explains each reason before the click. Archiving a department also archives its positions and switches off its chains; restoring it brings back only the department, and positions are restored one by one on purpose. Later slices add their own reasons through `ARCHIVE_BLOCKERS` (Slice 5: open requests).

### D-060 No reporting cycles
A department cannot sit under itself, a position cannot report to itself through any chain, and a person's reporting line (a named override or the position's line) cannot lead back to them, including when position lines and overrides combine. Structure changes are serialised with one database lock, and every check reads stored data, not what the caller passed in.

### D-061 Approval chains
A chain belongs to a department and a kind of request (`DEFAULT` applies when there is no more specific one). It has up to 6 ordered steps; each step is a position, a role, a named person, the department head, or the requester's line manager. A chain is replaced as a whole and the before and after are audited. The system works out the real approver when a request is submitted; requesters never choose (rule 11). Nothing uses chains until the Approval Centre (Slice 5), which also enforces that nobody approves their own request.

### D-062 Department heads
A head must hold a position in the department and have an active account. If they leave it, the head post is cleared and the change recorded.

### D-063 Sync policy
Departments, positions and staff assignments are reference data: devices may read them offline later but never change them (structure is online-only, server wins). Approval chains are online-only and are never cached on devices. The organisation API returns names only; no contact details.

### D-064 Staff names are visible to anyone with administration VIEW
Searching for people (to assign or pick an approver) returns names and usernames of active accounts to anyone with `administration.VIEW`, which includes the Board Member by default. Say if that should be narrower (D-034 review).

## Pending owner decisions

Still open in `docs/SCHEMA.md` section 9: approval hierarchy tables (stored in Slice 4, D-061; whether they merge with workflow steps is still open), single versus multi-step approvals, requester-as-only-approver policy, data protection review and hosting region (firm, because the database is in the cloud). Scope semantics are now D-035; default grants are D-034 and need your review.

Also: ratify the TZS tiers (D-020) before Slice 11, and confirm the builder's choices in D-022.

Needed before: Slice 5 (approval chains, requester policy), Slice 11 (TZS ratification), and before deployment (hosting region, data protection review).

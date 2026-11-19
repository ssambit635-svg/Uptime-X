# Delivery progress — 19 November 2026

## Today's target

**First approximately 30% of Phase 1 (Observatory).** This is a planning estimate weighted toward
account and monitor configuration work, not a claim that 30% of every feature is implemented.
Because the repository initially contained only the PRDs, the prerequisite Phase 0 scaffold is included.

## Implemented in this slice

- [x] React + TypeScript + Vite / Tailwind app and responsive dashboard shell.
- [x] Modular FastAPI API with database-backed health endpoint and OpenAPI schema.
- [x] SQLAlchemy users, digest-only sessions and tenant-owned monitors.
- [x] Reversible PostgreSQL-compatible Alembic migration; SQLite development adapter.
- [x] Registration, login, verified session establishment, restoration, expiration and logout revocation.
- [x] Explicit non-production iframe-preview session transport for cookie-blocked browsers/proxies.
- [x] Optional built-dashboard entry point on the API port, avoiding JSON-only preview roots.
- [x] Argon2id hashing, generic login errors and bounded single-process auth limits.
- [x] Same-origin custom-header CSRF protection; no permissive CORS.
- [x] Monitor create, list, detail, edit, pause, resume and delete.
- [x] Public URL syntax/DNS/IP policy at configuration time, on create **and** URL edits.
- [x] Ten-monitor account quota, duplicate-URL handling and validated interval/timeout settings.
- [x] PostgreSQL row-lock quota protection verified with concurrent create requests.
- [x] Explicit UNKNOWN/PAUSED states, `null` measurements and truthful future-feature labels.
- [x] Search, filter, confirmation dialogs, keyboard modal behavior and mobile navigation.
- [x] Unit/integration/security tests plus real-browser user journeys.
- [x] Dependency locks, secret ignores, local run instructions and architecture/security notes.
- [x] Dockerfiles, Compose topology and CI definitions (see verification caveat below).

## Still required for Phase 1

- [ ] Safe **execution-time** URL revalidation, actual-destination pinning and redirect validation.
- [ ] Bounded HTTP worker: timeout, TLS verification, byte cap and categorized errors.
- [ ] Real check schema/migrations, persistence and history API.
- [ ] Local scheduling/queue adapter and duplicate-result protection.
- [ ] Freshness policy: missing/stale results must remain UNKNOWN, not UP.
- [ ] Expected HTTP status/latency policy configuration and classification from real results.
- [ ] Real timing measurements, uptime calculations and explicitly labelled sample windows.
- [ ] Dashboard history/charts driven solely by persisted checks.
- [ ] Controlled-network worker/security tests and complete add → check → history E2E.
- [ ] Operational heartbeat/freshness instrumentation and launch safety review.

Distributed AWS scheduling/workers belong to Phase 2; incident intelligence and notifications to
Phase 3; deterministic Playground scenarios to Phase 4; Recovery Lab to the later privileged milestone.
None is silently stubbed as implemented.

## Verification record

Executed locally in Arena:

- **126 backend tests passed on PostgreSQL 16.2**, including concurrent quota enforcement.
- **125 passed + 1 intentional PostgreSQL-only skip on SQLite**; measured backend line coverage: **96.85%**.
- **28 frontend component/client/session tests passed**.
- **7 Chromium E2E journeys passed**: persisted lifecycle, unsafe URL rejection/focus restoration,
  tenant isolation, mobile layout/navigation, cookie-blocked iframe registration/login/reload,
  storage-denied page-lifetime sign-in, and actionable cookie-only session failure recovery.
- The iframe regressions load the real built frontend against real APIs, with every Cookie and
  Set-Cookie stripped at the controlled proxy boundary (including partitioned cookies). They do not
  claim access to the user's actual Arena browser.
- Additional earlier browser smoke check: HTTPS cross-site iframe registration/session restoration,
  mobile viewport containment, and no uncaught browser errors.
- Frontend production build, TypeScript, ESLint, Prettier and Ruff checks passed; npm audit reported
  zero known vulnerabilities at this verification time.
- Migration upgrade, schema-drift check, downgrade and re-upgrade passed on SQLite and PostgreSQL.
- Clean runtime installation from the hash-locked Python dependencies loaded the API successfully.

Repeatable commands are in the README and CI definitions. Docker is not installed in this workspace,
so the **container build/Compose smoke test has not been run here**. No AWS or Vercel deployment,
paid infrastructure, GitHub push or remote CI run is implied.

## Sign-in repair

The user reported sign-in failure with a JSON `HTTP_ERROR / Not Found` screenshot. The API root
reproduced that response, and logs separately showed successful login followed by protected 401s.
The preview now serves the dashboard on both active entry points, verifies an authenticated request
before opening the workspace, and supports a short-lived, explicitly opted-in non-production session
transport when cookies are blocked. Existing accounts and monitor data were not reset. Production
remains HttpOnly-cookie-only; see [ADR 002](decisions/0002-preview-sessions.md) for the tradeoff.

## Important release limits

- This slice stores configuration; it does not monitor availability.
- No email verification, password recovery, account deletion, teams or production abuse controls yet.
- Auth limits are per process, not a distributed defense.
- SQLite is a local convenience, not the concurrency/production target.
- Deletion is currently hard deletion of configuration only. Introduce archival/retention rules before
  real check and incident history is added.
- Production needs TLS, shared rate limits, outbound worker isolation, backups/restore testing,
  dependency/security review, budgets, observability and deployment review before public launch.

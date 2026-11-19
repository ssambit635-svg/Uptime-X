# UptimeX

**The Internet’s Health, Under One Roof.**

A website observability and resilience-learning platform, built in working vertical slices.

## Current work: Observatory + distributed monitoring

Phase 1's real-check workflow is implemented and locally tested. Phase 2's SQS adapter, regional
workers and staging infrastructure are implemented, but **live AWS acceptance is still pending**.
This is not a production launch or a claim that an AWS deployment exists. **The owner approved a
pre-AWS implementation PR; account setup, deployment and live drills will follow after merge.**
Live regional checks, retries and DLQ/replay verification remain required before declaring Phase 2
operationally complete. No workflow deploys paid AWS resources automatically.

### Working in the application

- Responsive React/TypeScript dashboard, keyboard-accessible dialogs and explicit **REAL** provenance.
- Register, sign in, restore and revoke sessions; Argon2id passwords and digest-only expiring sessions.
- Explicit non-production iframe-preview session fallback for cookie-blocked previews.
- Tenant-owned monitor CRUD, pause/resume, quota 10, duplicate-target protection and policy editing.
- Bounded HTTP checks: public DNS/IP policy, pinned connections, Host/SNI/certificate verification,
  redirect revalidation, timeout/response caps and categorized evidence. No response bodies are stored.
- Separate scheduler and worker processes, durable jobs/outbox, lease fencing, retries, retention and
  idempotent check persistence. The local transport is a **database queue**, not an emulated AWS region.
- Freshness-aware UP / DEGRADED / DOWN / UNKNOWN / PAUSED, real check history and queued check-now.
- Measured availability, average/median/p95 HTTP latency, sampling coverage, sample-based downtime
  estimates, regional comparison, charts with null gaps and accessible chart tables.
- Global monitor / Analytics views with actual scheduler/worker heartbeats and tenant-scoped job health.
- SQS transport and operator CLI, two-region ECS/EventBridge/Terraform definitions, bounded worker
  scaling, operational alarms, private RDS, distinct database identities and a private bootstrap task.

### Not delivered yet

The AWS deployment/drills required to close Phase 2 are **not verified**. All six checks passed in
[pre-AWS CI](https://github.com/ssambit635-svg/Uptime-X/actions/runs/44590147987),
including provider-aware Terraform initialization/validation and the Docker Compose build/startup
smoke test. An account-specific plan, image scan/publication and live AWS drills remain open;
validation and mocked SDK tests do not prove a cloud deployment.

Incident lifecycle, customer notifications, Incident Detective, public status pages, Playground,
Recovery Lab and public-production hardening are not implemented. Configured failure/recovery
thresholds currently classify monitor state; they do **not** create incidents or alerts.

New to AWS? Start with the [plain-language post-merge guide](docs/aws-start-here.md). No AWS account
access or spending is needed to review and merge this implementation.

Read [progress and phase boundaries](docs/progress.md), [operations/deployment](docs/operations.md),
[security](docs/security.md) and [monitoring design](docs/decisions/0003-monitoring-pipeline.md).
Both original PRDs remain unchanged. After Phases 1 and 2 close, **four roadmap
phases remain: 3 Incident intelligence, 4 Playground, 5 Recovery Lab, 6 Production polish.**

## Local development

Requires **Python 3.11+** and **Node 22.12+** (Node 22 in CI/containers).

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r backend/requirements-dev.lock
npm ci --prefix frontend
alembic upgrade head
```

Run from the repository root, with the virtual environment activated in each Python terminal:

```bash
# Terminal 1 — HTTP API
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log --reload --reload-dir backend

# Terminal 2 — due-monitor scheduling and maintenance
PYTHONPATH=backend python -m app.workers.cli scheduler --loop

# Terminal 3 — actual bounded HTTP execution
PYTHONPATH=backend python -m app.workers.cli worker --loop

# Terminal 4 — same-origin frontend proxy
npm run dev --prefix frontend
```

Open **http://localhost:5173**, register, and add a public website **you own or are authorized to
monitor**. There are no seeded users, demo credentials or fabricated measurements. Creating a monitor
performs safe DNS validation; a separate worker makes the HTTP request after scheduling. Without a
scheduler/worker, checks remain queued/missing and status stays UNKNOWN. A queued check is not a
successful observation. Do not start a worker in a network-restricted sandbox and interpret its
transport failures as an independent public-Internet availability assessment.

Native development defaults to `.local/uptimex.db` (ignored by Git). Ordinary local and production
sessions use HttpOnly cookies, not browser-storage tokens. The browser only calls relative
`/api/v1/...` URLs. Vite proxies `/api`, preserving the incoming Host for CSRF protection.
`API_PROXY_TARGET` is a **server-side** setting; never put localhost backend URLs in browser code.

### PostgreSQL / Compose

```bash
docker compose up --build
# Open http://localhost:8080
```

Compose runs PostgreSQL, migrations, API, scheduler, worker and Nginx/frontend. PostgreSQL is exposed
only on local loopback; the API has no public Compose port. `postgres_data` preserves data.

```bash
docker compose down              # keeps data
# Destructive local reset only: docker compose down --volumes
```

Compose uses **local-development credentials**, not cloud secrets. Do not expose it publicly.
For native PostgreSQL, set a percent-encoded `postgresql+psycopg://...` `DATABASE_URL`, then migrate.
SQLite is only the small, single-host development adapter; distributed monitoring requires PostgreSQL.

## HTTPS embedded previews

Only for a trusted **non-production HTTPS preview**, enable `EMBEDDED_PREVIEW=true`. This uses
host-only `Secure; HttpOnly; SameSite=None; Partitioned` cookies. Where an embedding browser/proxy
blocks cookies, the frontend explicitly requests a short-lived opaque credential and sends it in
`X-UptimeX-Preview-Session`. `/auth/me` must succeed before the workspace opens. This is not an auth
bypass: expiry, ownership, rotation and logout revocation still apply.

Preview credentials default to **60 minutes** (`PREVIEW_SESSION_MINUTES`, 5–120), are kept in memory
and tab-scoped **sessionStorage**, never localStorage, and are cleared on expiry/logout. Denied storage
allows a page-lifetime session only. These credentials are JavaScript-readable: **never enable this
mode for public production**. Production rejects it and requires secure HttpOnly cookies/PostgreSQL.

A single-port app preview avoids accidentally opening a JSON-only API root:

```bash
npm run build --prefix frontend
EMBEDDED_PREVIEW=true FRONTEND_DIST=frontend/dist PYTHONPATH=backend \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log
```

Open the HTTPS **port 8000 app preview**. Rebuild after UI edits. `/` serves the app and `/api/...`
remains JSON. If an account already exists, choose **Sign in**; no account reset is needed.

## Verification

```bash
source .venv/bin/activate
ruff check backend tests
ruff format --check backend tests
pytest --cov=app --cov-report=term-missing --cov-fail-under=90
alembic check

npm run lint --prefix frontend
npm run format:check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
npm audit --prefix frontend --audit-level=high

cd frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

Run the same backend suite, including parallel scheduler/worker lease and owner-quota tests, on a
**disposable** PostgreSQL database ending in `_test`:

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/uptimex_test' pytest
```

Tests create/drop isolated schemas. Never point this at real data. SQLite explicitly skips the
PostgreSQL concurrency cases. Controlled checker tests use a test-only routed socket; production has
no allow-private flag. The measurement browser journey queues via the real API, measures an actual
controlled HTTP response, persists it through the job pipeline and reads it in the UI. It does **not**
claim public egress, real TLS against AWS or geographic execution. Preview-session regressions also
exercise built-frontend cookie-blocked iframe and storage-denied journeys.

CI runs both database suites, populated migration upgrade/backfill/drift/rollback/cascade checks,
lint/build/tests, browser journeys, container smoke tests and Terraform validation with a committed
provider lock. The destructive migration smoke helper (`tests/support/migration_roundtrip.py`) refuses
existing application tables and requires `APP_ENV=test` plus an empty disposable `*_test` PostgreSQL
database or `*_test.db` SQLite file; never use it on application data. Actual live AWS evidence is a
separate gate; see [the checklist](docs/operations.md#live-aws-acceptance-gate).

## API

- `/api/v1/health`: API/database liveness, not proof that a target or worker is healthy.
- `/api/openapi.json`, `/api/docs`: schema/reference.
- `/api/v1/auth/{register,login,me,logout}`: accounts and sessions.
- `/api/v1/monitors` and `/api/v1/monitors/{id}`: configuration and measured state.
- `POST /api/v1/monitors/{id}/{pause,resume}`: lifecycle; invalidates outstanding old-policy work.
- `POST /api/v1/monitors/{id}/check`: durable queue request, HTTP 202, 60-second per-monitor cooldown.
- `/api/v1/monitors/{id}/checks?limit=50&offset=0&region=local`: paginated actual check evidence.
- `/api/v1/monitors/{id}/analytics?window=24h`: current-revision 24h / 7d / 30d / 90d statistics;
  optional `region`. Maximum 100,000 samples per request; select a shorter window/one region if needed.
- `/api/v1/operations`: authenticated pipeline health. Job counts are scoped to the requesting owner;
  deployment heartbeat aggregates contain no other tenant's monitor data.

All unsafe requests require **`X-UptimeX-Client: web`** plus a valid session. Same-origin checks and no
permissive CORS protect writes. Never put passwords/session tokens in URLs, source or logs. Errors use
`{"error":{"code":"...","message":"..."}}` with safe validation-field details where appropriate.

## Repository layout

```text
frontend/                 UI, typed API client, component and browser tests
backend/app/              API, settings, auth, models, checker, jobs, analytics, worker CLI
backend/migrations/       Reviewed migrations (0002 rollback destroys check history)
infrastructure/terraform/ Two-region staging stack and reusable network/worker-pool modules
tests/                    Unit, API, monitoring, security and offline infrastructure contracts
docs/                     Progress, operations, security and architecture decisions
.github/workflows/        CI; does not auto-deploy paid AWS resources
```

Python input requirements are `backend/requirements*.txt`; both committed hash locks pin transitive
versions. Refresh on Python 3.11 with `pip-tools`, then repeat all checks:

```bash
pip-compile --generate-hashes --strip-extras -o backend/requirements.lock backend/requirements.txt
pip-compile --generate-hashes --strip-extras -c backend/requirements.lock -o backend/requirements-dev.lock backend/requirements-dev.txt
```

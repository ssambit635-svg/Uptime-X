# UptimeX

**The Internet’s Health, Under One Roof.**

A website observability and resilience-learning platform, built in working vertical slices.

## Current release: Phase 1, first ~30% slice

This is a **development foundation**, not a running uptime service or a production-ready release.
The percentage is a scope estimate, not a measured completion score.

### Working today

- React + TypeScript + Vite dashboard, Tailwind styling, responsive navigation and accessible dialogs.
- Registration, sign-in, session restoration and sign-out.
- Argon2id password hashes and expiring, revocable HttpOnly cookie sessions. Only token digests are stored server-side.
- Explicit non-production iframe-preview session fallback when an embedding browser/proxy blocks cookies.
- Tenant-owned monitor creation, listing, detail, editing, pause/resume and confirmed deletion.
- PostgreSQL persistence, Alembic migrations and an explicit SQLite development/test adapter.
- Public HTTP(S) URL validation, bounded DNS resolution, prohibited-address rejection and account quotas.
- Honest empty states: monitors are **UNKNOWN** or **PAUSED**; measured fields are `null`.
- API health check, request IDs, sanitized errors, structured request logs and automated tests.
- Docker Compose and GitHub Actions definitions.

### Not implemented yet

Real HTTP checks, scheduler/worker execution, redirects/DNS pinning at connection time, check history,
actual uptime charts, incident detection, notifications, regional workers, public status pages,
Playground, Recovery Lab and AWS/Terraform deployment. No request is sent to a target website by this
release; URL setup performs DNS lookups only. Never treat a saved URL as permanently safe to fetch.

See [the progress checklist](docs/progress.md), [security boundaries](docs/security.md) and
[architecture decisions](docs/decisions/0001-foundation.md). The original `.docx` and `.md` PRDs remain
unchanged and describe the **target**, not the current implementation.

## Local development

Requires **Python 3.11+** and **Node 22.12+**. Node 22 is used in CI and containers.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r backend/requirements-dev.lock
npm ci --prefix frontend
alembic upgrade head
```

Run these in two terminals from the repository root:

```bash
# Terminal 1 — with the virtual environment activated
PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log --reload --reload-dir backend

# Terminal 2
npm run dev --prefix frontend
```

Open **http://localhost:5173** and create your own account. There are no seeded users, shared demo
passwords or sample measurements. Normal local development and production use HttpOnly cookie
sessions, not browser-storage tokens. Configuration survives a restart in `.local/uptimex.db`; that
file and all secrets are ignored by Git.

The browser calls relative `/api/v1/...` URLs. Vite proxies `/api` to the API, preserving the incoming
Host so same-origin CSRF checks also work through a preview proxy. Do **not** put a backend localhost
URL in browser code. `API_PROXY_TARGET` is a **server-side** setting, not a `VITE_` variable.

### PostgreSQL instead of SQLite

For the full container topology:

```bash
docker compose up --build
```

Open **http://localhost:8080**. A migration service initializes PostgreSQL before the API starts;
Nginx serves the built frontend and proxies the API. PostgreSQL is exposed only on local loopback;
the API itself has no public Compose port. `postgres_data` preserves data across restarts.

```bash
docker compose down              # keeps data
# Destructive local reset only: docker compose down --volumes
```

The Compose credentials are **local-development defaults**, not production secrets. Do not deploy
this topology publicly. Native development can use PostgreSQL by setting `DATABASE_URL` to a
`postgresql+psycopg://...` connection string in `.env`, then running migrations. Percent-encode any
special characters in connection-string credentials.

### HTTPS embedded previews

For a **non-production preview behind an HTTPS proxy**, set `EMBEDDED_PREVIEW=true` on the API.
It sets host-only `Secure; HttpOnly; SameSite=None; Partitioned` cookies. Some embedding browsers or
preview proxies still do not return those cookies. In this mode only, the frontend can explicitly
request a short-lived opaque session in the login/register response and send it in
`X-UptimeX-Preview-Session`. This is the same server-validated, expiring, revocable session—not an
authentication bypass. The UI verifies `/auth/me` before opening the dashboard.

Preview credentials expire after **60 minutes** by default (`PREVIEW_SESSION_MINUTES`, range 5–120),
use tab-scoped **sessionStorage**, never localStorage, and are cleared on logout or expiry. If all
storage is denied, sign-in works in memory for the page lifetime; reload then requires sign-in again.
These preview credentials are JavaScript-readable: **do not use this mode for production or a public
launch**. Passwords are never stored in browser storage. Production rejects embedded-preview mode
and never issues or accepts this header credential; it requires PostgreSQL and secure HttpOnly cookies.
The CSRF header/origin checks remain enabled in every mode.

To avoid accidentally opening a JSON-only API preview, serve the built dashboard on the API's port:

```bash
npm run build --prefix frontend
EMBEDDED_PREVIEW=true FRONTEND_DIST=frontend/dist PYTHONPATH=backend \\
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log
```

Open the **port 8000 app preview** supplied by the HTTPS preview host. `/` serves the dashboard;
`/api/...` still serves the API. Rebuild after frontend changes. The two-terminal Vite setup above
remains available for hot reload. If registration reports that the email already exists, choose
**Sign in** with that account; no account reset is needed. A blocked cookie-only session now stays
on the form with an explicit **Open preview in a new tab** recovery action.

## Verification

```bash
# Backend + security (SQLite); the PostgreSQL-only concurrency case is explicitly skipped
source .venv/bin/activate
ruff check backend tests
ruff format --check backend tests
pytest --cov=app --cov-report=term-missing
alembic check

# Frontend
npm run lint --prefix frontend
npm run format:check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend

# Real browser: isolated cookie/Vite and built iframe-preview API/database processes
cd frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

To run the **same backend suite on real PostgreSQL**, create a disposable database whose name ends
in `_test`, and set `TEST_DATABASE_URL` for pytest:

```bash
TEST_DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/uptimex_test' pytest
```

**Tests create and drop isolated schemas/tables. Never point this variable at real data.** PostgreSQL
cases use unique temporary schemas and require schema-creation privileges; public migration tables
are left alone. The fixture rejects non-test PostgreSQL database names. URL/DNS security tests use controlled resolver responses;
Playwright uses public IP literals and makes no target HTTP requests.

CI is configured to run SQLite and PostgreSQL tests, migration drift/rollback checks, lint, formatting,
frontend tests/build, Chromium journeys and a Compose smoke test. A configured workflow is not a
claim that remote GitHub checks or a cloud deployment have run.

### API

- Health: `/api/v1/health`
- OpenAPI: `/api/openapi.json`
- Interactive reference: `/api/docs`
- Accounts: `/api/v1/auth/{register,login,me,logout}`
- Monitors: `/api/v1/monitors` and `/api/v1/monitors/{id}`
- Lifecycle: `POST /api/v1/monitors/{id}/{pause,resume}`

All unsafe requests must include **`X-UptimeX-Client: web`**. This custom header plus same-origin
validation and the absence of CORS permission protect authenticated writes. API clients also need
their session cookie (or the explicitly enabled development-preview credential described above).
Never put passwords or session tokens in source code, URLs or logs. Validation failures use
`{"error":{"code":"...","message":"..."}}`, with safe field details where relevant.

## Repository layout

```text
frontend/                 React UI, API client, component and browser tests
backend/app/              FastAPI routes, settings, auth, models, schemas, URL policy
backend/migrations/       Reviewed, reversible Alembic migrations
tests/                    Backend integration, security and unit tests
docs/                     Progress, security notes and architecture decisions
.github/workflows/        Checks and container/browser verification
```

Python dependency inputs are `backend/requirements*.txt`; committed `.lock` files pin transitive
versions and hashes. Refresh both with Python 3.11 and `pip-tools`, then re-run all checks:

```bash
pip-compile --generate-hashes --strip-extras -o backend/requirements.lock backend/requirements.txt
pip-compile --generate-hashes --strip-extras -c backend/requirements.lock -o backend/requirements-dev.lock backend/requirements-dev.txt
```

## Next vertical slice

Implement an independently validated, bounded HTTP checker with actual destination pinning,
redirect/response limits and controlled-network tests; persist real check results; then connect
scheduling, freshness-aware status and measured history to this dashboard. No incidents or charts
should claim data before that pipeline is verified.

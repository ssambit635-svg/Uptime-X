# Delivery progress — 19 November 2026

## Current scope and release gate

The earlier first ~30% of Phase 1 and preview sign-in repair were delivered through merged PR #1.
The current request supersedes that percentage: finish the rest of **Phase 1 (Observatory)** and
**Phase 2 (Distributed monitoring)**, following both original PRDs in this repository.

Both `UptimeX_Expanded_PRD_v1.md` and the complete original `.docx` were reviewed; neither was changed.
The owner explicitly selected **live AWS verification before opening the next PR**. Implementation,
local tests, SDK stubs, Terraform definitions and a Vercel connection are not substitutes. **No Phase
1/2 completion PR should be opened until the live gate in [operations](operations.md#live-aws-acceptance-gate)
passes.** No AWS deployment or paid resource creation has been performed by this work.

| Roadmap phase | Current status |
|---|---|
| 0 Foundation | Delivered in the earlier merged slice |
| 1 Observatory | Remaining application features implemented; local feature acceptance verified |
| 2 Distributed monitoring | Durable/SQS/regional implementation and staging IaC written; cloud acceptance still open |
| 3 Incident intelligence | Not implemented |
| 4 Playground | Not implemented |
| 5 Recovery Lab | Not implemented |
| 6 Production polish | Not implemented |

After Phases 1 and 2 actually close, **four roadmap phases remain (3–6)**. The open AWS acceptance
work is unfinished Phase 2 work, not a claim that the whole current request is complete.

## Phase 1 implementation

- [x] Preserve auth/session/tenant isolation and the explicit non-production preview sign-in repair.
- [x] Monitor CRUD, quota/dedup, pause/resume and configurable interval/timeout/HTTP/latency policies.
- [x] Execution-time URL/DNS revalidation, public IP pinning, actual-peer validation and original Host/SNI.
- [x] Bounded real HTTP GET, certificate verification, redirect revalidation, timeout/header/body caps.
- [x] Categorized DNS/TCP/TLS/TTFB/total timing evidence without storing response bodies or credentials.
- [x] Real-check migration, durable scheduler/jobs, separate worker process and unique/fenced persistence.
- [x] Current-revision freshness/regional states; missing/inconclusive/stale results are never UP.
- [x] Owned, paginated check history and 24h/7d/30d/90d analytics with explicit sampling/retention policy.
- [x] Observed availability, average/median/nearest-rank p95, sampling coverage and estimated downtime.
- [x] Measured UI, chart gaps, accessible trend table, regional comparison, filters and check-now queueing.
- [x] Active Global monitor / Analytics pages; observed worker/scheduler and tenant job health.
- [x] Controlled HTTP → persisted result → API → browser measurement journey; mobile/keyboard checks.

Configured failure/recovery thresholds here classify visible monitor state only. They do not deliver
Phase 3's incident lifecycle, notification delivery, timeline or Incident Detective.

## Phase 2 implementation and remaining acceptance

- [x] PostgreSQL row locking/CAS claims; concurrent schedulers, duplicate delivery, lease expiry/fencing.
- [x] Durable SQS outbox, UUID/version/region-only envelopes, bounded AWS SDK calls and regional consumers.
- [x] Infrastructure failures retry with jitter, become DEAD after bounded attempts, and never invent downtime.
- [x] Source queue/DLQ/redrive definitions in each region; malformed/misrouted messages are not acknowledged.
- [x] Confirmed operator fresh replay, dead-job inspection, retention and safe stale-job reconciliation.
- [x] Own-container probes, structured CloudWatch EMF metrics, outbox/dead-job/queue/heartbeat alarms.
- [x] Two-region Terraform network/worker modules, private RDS, TLS ALB, separate API/worker/scheduler IAM,
  Secrets Manager bootstrap/replica, immutable images, capped autoscaling and explicit budget alerts.
- [x] EventBridge minute scheduler/daily retention definitions; deploy disabled by default.
- [x] Compose scheduler/worker services, expanded CI and deployment/replay/rollback/cleanup documentation.
- [x] Offline strict HCL syntax/format checks and infrastructure policy contracts.
- [ ] Provider-aware `terraform init/validate/plan` on an equipped runner; review/commit its provider lock.
- [ ] Build/scan/publish the actual image; verify complete Compose topology on a Docker-capable runner.
- [ ] Authorized AWS staging account/runner, approved regions/spend, state backend, HTTPS certificate/DNS.
- [ ] Actual bootstrap, secret replication, regional DB TLS/egress, ECS and EventBridge deployment.
- [ ] Real regional measurements, target failure/recovery, duplicate delivery, durable retry and actual
  SQS DLQ/alarm/replay drills, capped scaling and verified cleanup. **Mandatory before PR.**

The stack is **staging-only**, not a public-production deployment. Single-primary RDS/one NAT per region
are conscious starting tradeoffs, not a multi-region HA claim. No incident/simulation/lab tables or
permissions were silently introduced to inflate Phase 1/2 completion.

## Local verification record

Executed in this workspace for the current implementation:

- **242 backend tests passed on real local PostgreSQL**, including concurrent scheduler/consumer leases.
- **238 passed + 4 intentional PostgreSQL-only skips on SQLite**, **96.58% backend line coverage**.
- **39 frontend component/client/session tests passed** across 7 files.
- **8 Chromium E2E journeys passed**, including the new queued check → actual controlled HTTP exchange →
  committed result → chart/history/regional views flow, with actual modal keyboard/mobile checks.
- The controlled HTTP test boundary is test-only and not copied into the image. Its timings are measured,
  not filled-in samples; it does not prove public Internet egress, real geographic execution or AWS TLS.
- Existing cookie-blocked iframe/storage-denied/sign-in regression journeys still pass against the real
  built UI/API. They do not claim inspection of the user's actual browser/proxy.
- Ruff, ESLint, Prettier, TypeScript and production Vite build passed. Chart code is lazy-loaded:
  approximately 289 kB main JS / 88 kB gzip plus 410 kB chart JS / 116 kB gzip, no oversized-chunk warning.
- npm audit reported **0 known vulnerabilities** at verification time.
- Both Python hash locks regenerated; a **clean hash-locked dev installation and pip check passed**.
- SQLite and PostgreSQL migration upgrade/drift/0001 downgrade/base downgrade/re-upgrade passed.
- The bootstrap's real SQL grants were exercised against disposable PostgreSQL: API create/read/delete,
  worker schedule/claim/persist/prune/heartbeat and cascading deletion work with restricted roles.
  Worker identity reads/monitor deletion/schema creation and API evidence mutation were denied.
  The SDK/TLS boundary in that local permission exercise was controlled, not an RDS verification.
- All 9 Terraform files passed strict HCL syntax/formatting via a WASM HCL formatter; 13 offline
  infrastructure contracts are included in the backend suite. **Not provider-aware validation/plan.**

The local workspace lacks Docker/Terraform/AWS CLI and authorized AWS access. Container/provider checks
are delegated to the CI/equipped-runner steps; cloud drill results remain explicitly unclaimed.
See the workflow's actual run for remote check results, not this local evidence record. No workflow
in this repository automatically deploys paid AWS resources.

## Remaining roadmap

1. **Phase 3 — Incident intelligence:** idempotent incidents, lifecycle/timeline, notifications, Detective.
2. **Phase 4 — Playground:** deterministic isolated scenario engine, three scenarios, topology/challenges.
3. **Phase 5 — Recovery Lab:** isolated AWS lab, privileged approvals/templates, audit, emergency stop/cleanup.
4. **Phase 6 — Production polish:** identity/abuse controls, security/load/restore/cost review and public demo.

Public status pages, email verification/recovery, account deletion, shared rate limits, aggregate history,
production HA/restore tests and exported tracing remain future work, not hidden implemented features.

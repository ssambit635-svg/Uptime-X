# ADR 003 — Durable, bounded monitoring before incident intelligence

- Date: 2026-11-19
- Status: Application design implemented and locally verified; AWS deployment acceptance pending.
- Scope: Phases 1 and 2 of both original UptimeX PRDs.

## Decision

Keep the modular FastAPI API. Run scheduling and HTTP execution as separate processes. Store real
jobs, leases and observations in PostgreSQL; use a database queue for explicit single-host local
work and regional standard SQS queues for AWS. EventBridge Scheduler invokes a one-off Fargate
scheduler every minute; it does not create a schedule per monitor. ECS regional services consume
only their assigned queue. This bounds cloud resources and avoids API-process background workers.

The scheduler locks due monitor rows (`SKIP LOCKED`), advances the next slot without catch-up bursts,
and inserts at most one active job per monitor/region/revision under that lock. The same lock is
used by manual queueing and operator replay. A PostgreSQL uniqueness constraint protects exact slots.
The SQS outbox is persisted before publication. Sending before marking published may duplicate a
message; losing an observation silently is worse than duplicate delivery.

Consumers take compare-and-swap, token-fenced leases. Network execution holds no DB transaction.
Completion takes the monitor/job locks again, verifies current policy, state, token and unexpired
lease, then atomically writes one unique result for that job. A crash after commit/before SQS delete
is safe. Pausing, changing policy/target/regions, or resuming creates a new policy revision and
cancels old active jobs. Deleting a monitor cascades its jobs/history. Old-policy evidence is still
readable before deletion but cannot classify the current configuration.

Worker bugs/DB failures are infrastructure failures, not fabricated target FAILURE checks. They
retry with capped exponential backoff plus jitter, then remain operator-visible as DEAD. Expired
leases are reconciled; abandoned jobs older than one configured interval are cancelled rather than
blocking every future slot. SQS poison/misrouted/DEAD deliveries are not acknowledged and can reach
AWS's DLQ. A DLQ can also contain a duplicate of an already-completed job: inspect durable state
before taking action. Never automatically redrive everything.

## HTTP boundary

- GET only, no custom authentication/headers/cookies/proxy forwarding, only ports 80/443.
- Validate syntax/literal addresses, resolve bounded A/AAAA responses, require every answer public.
- Dial a numeric public address, verify the peer, preserve original Host/TLS SNI and CA/hostname checks.
- Revalidate every redirect, maximum 3; reject HTTPS downgrade, private rebinding and unsafe locations.
- Whole-check deadline at most 10 seconds, header bound, 256 KiB response cap, no decompression or
  response-body persistence. One pinned connection attempt per hop; not a load generator/scanner.
- Policy/size/refusal results are UNKNOWN. Observed DNS/timeout/TLS/HTTP failures are categorized,
  not asserted as a precise root cause. Missing worker network capability is UNKNOWN/WORKER_NETWORK.
- Initial AWS VPCs have IPv4 egress, private task subnets, no inbound worker rules, restricted egress
  ports, separate DB credentials and NACL rules denying HTTP(S) to private ranges. AWS link-local
  credential/DNS traffic has platform exceptions; socket-level policy is still mandatory.

## Classification and measurement contracts

- Missing, inconclusive, superseded or stale evidence is never UP. Freshness tolerance is one
  configured interval plus 60 seconds; both scheduled and observed timestamps matter.
- Per region, failures must meet the configured threshold (default 3) to become DOWN. After such a
  run, recovery needs configured consecutive successes (default 2). A slow valid response is DEGRADED.
- All current regions UP → UP; all DOWN → DOWN; conclusive disagreement/slow → DEGRADED; any UNKNOWN
  → UNKNOWN. PAUSED is intentional configuration, not an outage.
- These are display-state rules, not an incident lifecycle. Phase 3 owns incident transitions,
  immutable timelines, notification delivery, root-cause hypotheses and Incident Detective.
- Availability is successful eligible **samples / eligible samples** (UP/DEGRADED/FAILURE). Missing,
  paused and UNKNOWN samples are neither success nor failure. Coverage is displayed separately as
  distinct observed region/time slots / expected slots since the current revision began.
- HTTP latency statistics exclude checks with no HTTP response. p95 is nearest-rank; trend averages
  cover 120 actual buckets and null buckets stay gaps. Regional metrics use the same policy.
- Downtime is a capped, sample-based estimate (failed samples × interval / selected region count),
  not continuous event-derived downtime or an SLA. No inference of customer impact from HTTP alone.
- Analytics use the current revision only, while history is explicitly all revisions. Raw retention
  defaults to 90 days (operator configurable down to 1); older windows may be incomplete. There is
  no historical aggregate store or partitioning yet. Requests over 100,000 samples fail explicitly.

## AWS/operator boundary

API, scheduler and regional worker IAM roles are separate. API tasks cannot publish queue jobs or
change cloud resources; scheduler tasks only publish configured queues; workers consume only their
region's queue. A one-off, operator-invoked private bootstrap task holds privileged DB access, migrates
with the RDS-managed master secret and publishes separate API/worker DSNs to Secrets Manager. Normal
services never hold the schema-owner identity. AWS credentials come from task roles, not app config.

Images are immutable digest references when services are enabled. Staging starts disabled; it still
provisions paid NAT/RDS/ALB resources, so plan/cost approval is required before any apply. Budget
notifications are alerts, not a spending cap. The stack is intentionally staging-only: single-primary
RDS and one NAT per region are not a claim of multi-region database resilience or production HA.

CloudWatch EMF logs record heartbeats, scheduled/persisted throughput, outbox lag, dead jobs and
sanitized error categories. SQS age/depth/DLQ alarms, worker/scheduler silence, API and DB alarms are
operational alerts, separate from Phase 3's customer notifications. API request IDs and job IDs give
correlation; an OpenTelemetry collector/exported distributed-trace pipeline is not implemented yet.

## Verification and tradeoffs

Controlled HTTP/security tests, PostgreSQL parallel claims/schedulers, policy fencing, migrations,
SQS SDK contracts, restricted DB-role exercises, UI tests and browser add → queue → measured history
cover local acceptance. [CI for implementation commit `0c781ea`](https://github.com/ssambit635-svg/Uptime-X/actions/runs/44585023061)
also passed clean dependency installs/full suites, actual Docker Compose build/startup and
provider-aware Terraform initialization/schema validation. Neither establishes AWS IAM/network/secret
replication, Scheduler dispatch, regional geography, real broker redrive, autoscaling or successful
cloud deployment. All require the [separate live acceptance record](../operations.md#live-aws-acceptance-gate)
before Phase 2 is called operationally complete. The owner approved a pre-AWS code PR and deferred
account setup/deployment until after merge; that approval changes delivery order, not cloud evidence.

At this scale we deliberately do not add Redis coordination, Kubernetes, per-monitor AWS schedules,
incident tables, synthetic simulation data, exports or a privileged lab executor. Follow-on production
work includes shared abuse controls, partitioning/aggregates, HA/restore drills and deeper tracing.

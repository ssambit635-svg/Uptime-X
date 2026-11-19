# Monitoring operations and staging deployment

**Status: live AWS acceptance has not run. Do not open the Phase 1/2 PR until the gate below passes.**
This runbook and the Terraform files are implementation, not evidence that cloud resources exist.

## Operating model

| Process | Responsibility | Not a responsibility |
|---|---|---|
| API | Auth, tenant configuration, measured reads, durable manual enqueue | Target HTTP execution, AWS infrastructure changes |
| Scheduler | Due rows, lease/stale reconciliation, SQS outbox, operational metrics | Catch-up traffic bursts, invented historic checks |
| Worker | Its regional queue, safe HTTP measurement, fenced result commit | Incidents, cloud remediation, arbitrary internal requests |
| Operator task | Inspect dead jobs, deliberate fresh replay, retention | Automatic bulk replay or historic success backfill |
| Bootstrap task | Privileged migrations and restricted DB identity provisioning | HTTP endpoint or continuously running service |

Run native local workers with `PYTHONPATH=backend python -m app.workers.cli {scheduler,worker} --loop`.
A command without `--loop` is one iteration. Compose supplies both loops and health probes. Local
scheduler loops prune hourly; AWS has a daily retention task. Database transport is labelled `local`.
Do not label local processes as AWS regions just to make a map appear healthy.

Defaults: 300-second checks, 10-second target timeout, 3 failures before DOWN, 2 successes to recover,
10 monitors per owner, at most 3 configured regions, 90-second lease, 5 application attempts, capped
backoff plus jitter. One worker task executes one check at a time. SQS long-polls one message for up
to 20 seconds; visibility must be at least the configured lease and comfortably exceed check/commit
budgets. The staging stack uses a source queue and DLQ per region, visibility 90s and redrive after
5 receives. Broker receive counts and durable application attempts are **different counters**.

## Measurement/retention contract

- Health endpoint = API/DB only. Use authenticated `/operations` for pipeline evidence.
- Heartbeat probes identify their **own container**, not any healthy peer. Fleet views use 90-second
  worker / 180-second scheduler freshness. Check freshness is interval + 60 seconds.
- No fresh trustworthy regional result → UNKNOWN. Paused is PAUSED. Missing/inconclusive data is
  not success. See [ADR 003](decisions/0003-monitoring-pipeline.md) for exact classification/math.
- History is all revisions; analytics are current revision only, explicit 24h/7d/30d/90d windows.
  Pausing/resuming or changing check policy invalidates old work and begins new analytics eligibility.
- Raw jobs/results are retained 90 days by default (`CHECK_RETENTION_DAYS`, 1–90). Terminal jobs older
  than that and their cascading check rows are deleted; heartbeat records expire after 7 days.
- There are no long-term aggregate tables. A 90-day window may be incomplete after a shorter retention
  setting, late deployment or outages. Coverage makes gaps visible; downtime is only a sample estimate.
- Manual checks have a 60-second cooldown. Existing active work is reused, not duplicated. Schedule
  downtime does not trigger a catch-up burst. Stale queued slots are cancelled, not backfilled.
- Monitor deletion is **hard deletion**, cascading jobs/history. There is no archive/restore UI yet.

## Migrations and rollback

Back up first; stop scheduler/workers and API writes during a release migration. Never run migrations
inside every web/worker container startup. Apply once using a schema-owner identity, then start normal
services with restricted identities. Verify `alembic upgrade head` and `alembic check`.

`0002` adds monitoring policy, durable jobs, results and heartbeats while preserving existing users,
sessions and monitor configuration. Existing monitors start with `local` region defaults. When moving
existing local data to an SQS deployment, explicitly edit monitor region selections to the deployed
regions; do not silently attribute old local observations to AWS.

**Downgrading 0002 → 0001 permanently drops all check jobs, check history, heartbeats and policy fields.**
Export/backup evidence first. Prefer rolling back a compatible application image while retaining the
schema. A DB rollback is a separate approved operation, not automatic image-deployment rollback.
Practice upgrade/drift/downgrade/re-upgrade only on disposable databases. RDS snapshots are not a
substitute for a tested restoration procedure; a full restore drill remains a production-launch gate.

## Cloud prerequisites and cost approval

Use an isolated **staging AWS account**, commercial partition, Terraform 1.10+, AWS CLI v2, Docker,
Python/Node and `jq` on an AWS-capable runner (SSO/short-lived OIDC/task role). Never paste access keys,
RDS passwords or session credentials into chat, Git, shell history or logs. Do not enable shell tracing.
The Arena sandbox used for local work has no AWS credentials/CLI/Docker/Terraform or AWS network access.
A Vercel connection is not an AWS worker deployment.

Before provisioning, an authorized owner must approve:

1. Account ID, two regions (examples default to Mumbai `ap-south-1` and Singapore `ap-southeast-1`),
   resource owner tag, operator email, monitoring permission for the test endpoints, and a spend limit.
2. A region-local, validated ACM HTTPS certificate, owned DNS name and explicit DNS mapping to the ALB.
3. An existing private, encrypted, versioned S3 Terraform state bucket with TLS-only access and locking.
   Limit state access to the deployment role; do not commit state/plans or use a public bucket.
4. The actual Terraform plan and a current cost review. The stack provisions **paid resources even
   with services disabled**: two NAT gateways, ALB, RDS, storage, logs, cross-region traffic and later
   Fargate/scheduled tasks. No free-tier or exact-price promise is made. Budget alerts can be delayed
   and are **not a hard spending cap**. Example `monthly_budget_usd` is not spending authorization.
5. Time-boxed verification and cleanup ownership. RDS/ALB deletion protection deliberately blocks
   accidental teardown. Snapshots/secrets can continue to incur costs after services are stopped.

The stack is staging-only, with private IPv4 task subnets in two AZs per region, one NAT per region,
peered access to one primary-region RDS instance, and worker task counts capped at 1–3 per region.
This is **not** multi-region database failover or production HA. IPv6-only targets require a compatible
network; lack of a local route is UNKNOWN/WORKER_NETWORK, not proof of a target outage.

## Deployment sequence (not executed in AWS yet)

All commands below start at the repository root. Use the approved account/regions, not blindly the
example defaults. First commit/review the current branch and require green CI; never deploy a dirty
working tree or unreviewed dependency/image changes.

### 1. Validate and review a disabled initial plan

```bash
cp infrastructure/terraform/staging.tfvars.example infrastructure/terraform/staging.tfvars
# Edit ignored staging.tfvars: actual owner, certificate ARN, email and approved budget.
# Keep enable_services=false and app_image="" initially.

terraform -chdir=infrastructure/terraform fmt -check -recursive
terraform -chdir=infrastructure/terraform init -backend-config=../../.local/staging-backend.hcl
terraform -chdir=infrastructure/terraform validate
terraform -chdir=infrastructure/terraform plan -var-file=staging.tfvars -out=../../.local/staging-initial.tfplan
# Owner reviews account, resources, IAM, network paths and cost before explicitly applying:
terraform -chdir=infrastructure/terraform apply ../../.local/staging-initial.tfplan
terraform -chdir=infrastructure/terraform output -json deployment > .local/staging-deployment.json
```

The ignored backend file supplies `bucket`, `key`, `region`, `encrypt=true`, and `use_lockfile=true`.
Create `.local` first if absent. No provider credentials or secret values belong in these inputs.
`terraform init -backend=false && terraform validate` in CI validates schemas without applying paid
resources; it does not verify live permissions/networking. Commit the generated provider lock file
from the equipped runner after review; never commit `.terraform`, state, plans or account tfvars.

### 2. Build and publish an immutable image

The backend Dockerfile builds the frontend too, installs hash-locked runtime Python dependencies,
adds the official RDS CA bundle, and runs as UID 10001. Runtime tasks are read-only. API serves the
built app on the same origin. Test container builds/Compose before publishing.

```bash
REPOSITORY=$(jq -r .image_repository .local/staging-deployment.json)
REGISTRY=${REPOSITORY%%/*}
# Set PRIMARY_REGION to the approved region.
aws sts get-caller-identity  # verify account/role without printing credentials
aws ecr get-login-password --region "$PRIMARY_REGION" | docker login --username AWS --password-stdin "$REGISTRY"
TAG=$(git rev-parse HEAD)
docker build --platform linux/amd64 -f backend/Dockerfile -t "$REPOSITORY:$TAG" .
docker push "$REPOSITORY:$TAG"
# Wait for/review the ECR scan; remediate unacceptable findings before release.
aws ecr describe-images --region "$PRIMARY_REGION" --repository-name "${REPOSITORY#*/}" --image-ids "imageTag=$TAG" --query 'imageDetails[0].imageDigest' --output text
```

Set `app_image` in ignored tfvars to `REPOSITORY@sha256:...`, never `latest`. Plan/review/apply with
services still disabled to update task definitions. Re-export deployment outputs. Keep old tagged
images for rollback; lifecycle policy only expires untagged remnants.

### 3. Run the private bootstrap/migration task once

Normal tasks must never receive RDS's master password. Bootstrap reads the RDS-managed secret inside
a private task, migrates and writes separate API/worker DSNs to Secrets Manager. API cannot alter
check evidence; workers cannot read identities, delete monitors, create schema or change AWS resources.
Rerunning bootstrap reuses existing passwords. It is **not** a password rotation/revocation system;
add reviewed rotation procedures before production. Do not place `aws_secretsmanager_secret_version`
values/passwords in Terraform state.

```bash
CLUSTER=$(jq -r .cluster .local/staging-deployment.json)
BOOTSTRAP=$(jq -r .bootstrap_task .local/staging-deployment.json)
NETWORK=$(jq -c '{awsvpcConfiguration:{subnets:.private_subnets,securityGroups:[.bootstrap_security_group],assignPublicIp:"DISABLED"}}' .local/staging-deployment.json)
aws ecs run-task --region "$PRIMARY_REGION" --cluster "$CLUSTER" --task-definition "$BOOTSTRAP" \
  --launch-type FARGATE --network-configuration "$NETWORK" > .local/bootstrap-launch.json
jq -e '(.failures | length) == 0 and (.tasks | length) == 1' .local/bootstrap-launch.json
TASK=$(jq -r '.tasks[0].taskArn' .local/bootstrap-launch.json)
aws ecs wait tasks-stopped --region "$PRIMARY_REGION" --cluster "$CLUSTER" --tasks "$TASK"
aws ecs describe-tasks --region "$PRIMARY_REGION" --cluster "$CLUSTER" --tasks "$TASK" > .local/bootstrap-stop.json
jq -e '(.tasks | length) == 1 and (.tasks[0].containers | length) > 0 and all(.tasks[0].containers[]; .exitCode == 0)' .local/bootstrap-stop.json
```

Require `bootstrap: complete` in its CloudWatch log and review sanitized failure types otherwise.
Verify the worker secret's regional replica reports **InSync** before starting the secondary pool.
Never print secret contents to diagnose injection. DSNs require TLS `verify-full` with `/app/rds-ca.pem`;
RDS forces SSL. Normal API and worker roles are not schema owners.

### 4. Enable services and verify the deployment

Set `enable_services=true`, review the new plan and apply. ECS services use deployment circuit
breakers/steady-state checks; the minute scheduler and daily retention schedule become enabled.
Map owned DNS to the ALB, verify the certificate/HTTPS redirect, confirm the SNS operator email
subscriptions, then check the real app and `/api/v1/health` through that domain. Do not use the ALB
hostname as a substitute for certificate/DNS verification. Never enable embedded-preview mode here.

Inspect both worker services' task definitions, running task ARNs/regions, secret injection, private
networking, logs and own-container probes. Verify actual EventBridge invocations and scheduler
heartbeats, not merely a manually invoked scheduler. Run the entire acceptance matrix below before
calling Phase 2 complete or opening its PR. Record exact image digest and Git commit.

## Live AWS acceptance gate

**All unchecked. No live results are claimed.** Use only UptimeX-owned staging resources and a
public test fixture you own that can return 200, controlled 503, redirect, delayed response and bounded
large response. Never run failure/replay drills against customer production or arbitrary third parties.

| Required evidence | What must be observed in AWS |
|---|---|
| Clean build/deployment | Green CI, validated plan, successful image scan/bootstrap, healthy API + both regional ECS services |
| Scheduler | Real minute EventBridge dispatch schedules due jobs; disabled/paused monitors produce no checks; no catch-up burst |
| Real regional path | Create monitor through UI; each configured regional ECS task consumes its region's SQS job, fetches the owned public fixture and persists timings; UI/history/chart show actual timestamps and REAL provenance |
| Target failure/recovery | Owned fixture 503/timeout produces categorized FAILURE evidence and threshold-based state; recovery meets the configured successes, with no Phase 3 incident/notification claims |
| Redirect/TLS/network safety | Public redirect to prohibited destination is refused, TLS verification stays enabled, response limits hold; IPv4 egress and peered verify-full DB TLS work from each region |
| Duplicate delivery | Send the same known UUID envelope twice in the correct staging queue; exactly one result exists for that job, including commit-before-delete redelivery |
| Worker-internal retries | A controlled, time-bounded staging DB-write failure retries, increments durable attempts and ultimately creates DEAD work, **not target-downtime evidence** |
| Actual broker DLQ | Poison/misrouted envelope is retried (not deleted), reaches the configured regional SQS DLQ after bounded receives and triggers its real alarm |
| Deliberate replay | After restoring the fault, inspect DEAD UUID, invoke confirmed fresh replay, observe a new successful job/result; old evidence is unchanged; inspect/dispose only understood obsolete DLQ messages |
| Operability | Worker/scheduler silence, outbox/queue lag, internal errors and DLQ alarms are observable; SNS subscriptions confirmed; missing observations remain UNKNOWN, scale-out/in stays within approved cap |
| Retention/deletion | Run retention on disposable old records, never active leases; delete test monitor and verify cascades; rollback image and migration/backup procedures reviewed |
| Cleanup/cost | Remove test monitors, inspect all queues/DLQs, stop/clean up approved staging resources, verify final snapshots/secrets/charges and remaining resources |

For the broker test, use the queue's actual region and UUID-only format
`{"schema_version":1,"job_id":"<known UUID>","region":"<actual region>"}`. Never embed target URLs,
credentials or custom HTTP instructions in a job. Poison means an invalid bounded envelope, not a
malicious endpoint. SDK Stubber tests cannot mark this row passed.

A bounded DB-write fault can be exercised by an authorized operator holding a short exclusive lock
on `monitor_checks` in the otherwise empty **staging** database. Use one private admin connection,
set a short lock-acquisition timeout and an absolute statement timeout, execute a bounded `pg_sleep`
and ROLLBACK, and close the connection on every exit. Worker DB statements time out rather than
writing fake failure samples. Observe attempts/DEAD state through a separate connection/logs. Do
not leave persistent revoked grants, stop customer resources, extend the drill past the approved
window or introduce a production failure-injection API. If a different fault is chosen, document its
rollback and obtain approval first. This is a deployment test, not the future Recovery Lab feature.

Keep a sanitized acceptance record: commit/digest, account alias, regions, UTC start/end, task and
job IDs, per-case result, relevant metric/alarm timestamps, replay IDs, failure restoration and cleanup.
Exclude credentials, cookies, URLs with secret query strings and response bodies. Store evidence
securely; only a reviewed, sanitized summary should enter Git. Missing evidence keeps the gate open.

## Dead jobs, DLQ inspection and replay

From a configured local or **one-off private AWS operator task**, not the web API:

```bash
PYTHONPATH=backend python -m app.workers.cli dead-jobs
PYTHONPATH=backend python -m app.workers.cli replay --job-id "$JOB_ID" --confirm
PYTHONPATH=backend python -m app.workers.cli prune
```

For AWS, run a task using the deployed primary scheduler task definition/network, overriding the
`scheduler` container command with the replay/inspection command. Its publisher IAM role is limited
to the configured queues; it uses the restricted worker database secret. Capture task exit status
and sanitized logs. `--confirm` is mandatory, the original job must be DEAD, and the monitor must
still exist and be active. Replay applies **current policy and a new timestamp/UUID** (or reuses
already-active current work); it never rewrites historical results. Scheduled publication completes
the outbox-to-queue step. Paused/deleted monitors must not be force-executed.

Inspect SQS receive counts/attributes and durable job state before any delete/redrive. A malformed
message cannot be repaired by blindly redriving it. A completed duplicate needs no new check. A DEAD
job remains DEAD after a fresh replay; blindly moving its old envelope back repeats rejection. Use
small confirmed batches, keep operator evidence, and delete only specifically understood obsolete
receipts after recovery. Never purge an entire queue to hide failures.

## Troubleshooting and rollback

- **UNKNOWN/new check:** examine actual history, current revision, worker heartbeat, scheduler heartbeat,
  pending outbox/queue age, settings/regions and permission errors. Do not replace null metrics with zero.
- **Bootstrap failure:** check task exit and sanitized error type; verify IAM, private routes, RDS CA,
  master secret and DB schema. Do not use master credentials in normal services as a workaround.
- **Secondary secret/network failure:** verify replica InSync, its regional secret ARN, peering/routes,
  security groups/NACLs and RDS hostname TLS. Do not disable TLS or open 5432 to the Internet.
- **Queue lag:** check poison/duplicate receives, visibility vs lease, DB/worker throughput and capped
  autoscaling. Outbox publish failures are durable with retry delay; they must not disappear.
- **Service rollback:** choose the last verified digest and review/apply task definitions; ECS circuit
  breaker can roll back a failed service deployment, but does not roll back DB migrations or schedules.
- **Emergency stop/cleanup:** use an approved disabled-service Terraform plan. This stops services and
  schedules, not NAT/RDS/ALB charges. A reviewed teardown must explicitly disable deletion protection,
  name a non-conflicting final snapshot, retain/recover state, verify secondary resources and account
  for 7-day secret recovery/replicas. Never destroy state or leave an untracked paid stack.

Public launch still requires Phase 6's abuse/identity controls, HA/restore verification, deployment
security review, dependency/base-image pinning, performance/cost validation and deeper tracing.

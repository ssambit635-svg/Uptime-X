"""Durable scheduling/outbox, compare-and-swap leases and idempotent persistence.

Network execution never holds a database transaction. PostgreSQL supports multiple
schedulers/workers; SQLite is an explicit small local adapter, not cloud storage.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.telemetry import metric
from app.models.entities import CheckJob, Monitor, MonitorCheck, ServiceHeartbeat, utcnow
from app.services.checker import HTTPChecker, Observation

ACTIVE = ("QUEUED", "PUBLISH_PENDING", "RUNNING", "RETRY")
TERMINAL = ("COMPLETE", "CANCELLED", "DEAD")


def backoff(attempt: int) -> int:
    return min(300, 2 ** min(attempt, 8)) + random.randint(0, 3)


def invalidate_jobs(db: Session, monitor: Monitor) -> None:
    db.execute(
        update(CheckJob)
        .where(CheckJob.monitor_id == monitor.id, CheckJob.state.in_(ACTIVE))
        .values(state="CANCELLED", lease_token=None, lease_until=None)
    )
    monitor.revision += 1
    monitor.next_check_at = utcnow()
    monitor.revision_started_at = utcnow()


def enqueue_monitor(
    db: Session, monitor: Monitor, settings: Settings, now: datetime, *, reuse_existing: bool = True
) -> list[CheckJob]:
    if not settings.monitoring_enabled or monitor.is_paused:
        return []
    jobs = []
    for region in monitor.regions:
        if region not in settings.monitor_regions:
            continue
        existing = db.scalar(
            select(CheckJob)
            .where(
                CheckJob.monitor_id == monitor.id,
                CheckJob.region == region,
                CheckJob.revision == monitor.revision,
                CheckJob.state.in_(ACTIVE),
            )
            .limit(1)
        )
        if existing:
            if reuse_existing:
                jobs.append(existing)
            continue
        job = CheckJob(
            monitor_id=monitor.id,
            region=region,
            revision=monitor.revision,
            scheduled_at=now,
            available_at=now,
            state="PUBLISH_PENDING" if settings.queue_backend == "sqs" else "QUEUED",
        )
        db.add(job)
        db.flush()
        jobs.append(job)
    return jobs


def schedule_due(db: Session, settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    if not settings.monitoring_enabled:
        return 0
    monitors = list(
        db.scalars(
            select(Monitor)
            .where(
                Monitor.is_paused.is_(False),
                Monitor.next_check_at <= now,
            )
            .order_by(Monitor.next_check_at, Monitor.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    )
    count = 0
    for monitor in monitors:
        count += len(enqueue_monitor(db, monitor, settings, now, reuse_existing=False))
        # No catch-up bursts: missed slots stay missing, never synthetic successes.
        monitor.next_check_at = now + timedelta(seconds=monitor.interval_seconds)
    db.commit()
    return count


@dataclass(frozen=True)
class Claim:
    job_id: uuid.UUID
    lease_token: uuid.UUID
    target_url: str
    timeout: int
    expected_min: int
    expected_max: int
    slow_ms: int


def claim_job(
    db: Session, job_id: uuid.UUID, region: str, settings: Settings, now: datetime | None = None
) -> tuple[str, Claim | None]:
    now = now or utcnow()
    initial = db.get(CheckJob, job_id)
    if initial is None:
        return "ack", None  # Deleted monitor / expired history.
    monitor = db.scalar(select(Monitor).where(Monitor.id == initial.monitor_id).with_for_update())
    job = db.scalar(
        select(CheckJob)
        .where(CheckJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or job.state in ("COMPLETE", "CANCELLED"):
        db.rollback()
        return "ack", None
    if job.region != region:
        db.rollback()
        return "retry", None  # Misrouted/poison message must reach its DLQ, not disappear.
    if job.state == "DEAD":
        db.rollback()
        return "retry", None
    if (
        not settings.monitoring_enabled
        or monitor is None
        or monitor.is_paused
        or monitor.revision != job.revision
        or region not in monitor.regions
        or job.scheduled_at < now - timedelta(seconds=monitor.interval_seconds)
    ):
        job.state, job.lease_token, job.lease_until = "CANCELLED", None, None
        db.commit()
        return "ack", None
    if job.available_at > now or (
        job.state == "RUNNING" and job.lease_until and job.lease_until > now
    ):
        db.rollback()
        return "retry", None
    if job.attempts >= settings.max_job_attempts:
        job.state, job.last_error = "DEAD", "ATTEMPTS_EXHAUSTED"
        db.commit()
        return "retry", None
    token = uuid.uuid4()
    changed = db.execute(
        update(CheckJob)
        .where(
            CheckJob.id == job.id,
            or_(
                CheckJob.state.in_(("QUEUED", "RETRY", "PUBLISH_PENDING")),
                CheckJob.lease_until <= now,
            ),
        )
        .values(
            state="RUNNING",
            attempts=CheckJob.attempts + 1,
            lease_token=token,
            lease_until=now + timedelta(seconds=settings.job_lease_seconds),
        )
    )
    if changed.rowcount != 1:
        db.rollback()
        return "retry", None
    claim = Claim(
        job.id,
        token,
        monitor.target_url,
        monitor.timeout_seconds,
        monitor.expected_status_min,
        monitor.expected_status_max,
        monitor.slow_threshold_ms,
    )
    db.commit()
    return "execute", claim


def finish_job(db: Session, claim: Claim, observation: Observation, started_at: datetime) -> bool:
    initial = db.get(CheckJob, claim.job_id)
    if initial is None:
        return False
    monitor = db.scalar(select(Monitor).where(Monitor.id == initial.monitor_id).with_for_update())
    job = db.scalar(
        select(CheckJob)
        .where(CheckJob.id == claim.job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or job.state != "RUNNING"
        or job.lease_token != claim.lease_token
        or not job.lease_until
        or job.lease_until <= utcnow()
    ):
        db.rollback()
        return False
    if monitor is None or monitor.is_paused or monitor.revision != job.revision:
        job.state, job.lease_token, job.lease_until = "CANCELLED", None, None
        db.commit()
        return False
    # The job row lock + unique job_id prevent duplicate results even if SQS
    # redelivers after commit but before DeleteMessage. Fencing rejects old leases.
    changed = db.execute(
        update(CheckJob)
        .where(
            CheckJob.id == claim.job_id,
            CheckJob.state == "RUNNING",
            CheckJob.lease_token == claim.lease_token,
        )
        .values(state="COMPLETE", lease_token=None, lease_until=None, last_error=None)
    )
    if changed.rowcount != 1:
        db.rollback()
        return False
    db.add(
        MonitorCheck(
            job_id=job.id,
            monitor_id=job.monitor_id,
            revision=job.revision,
            region=job.region,
            scheduled_at=job.scheduled_at,
            started_at=started_at,
            checked_at=utcnow(),
            **observation.values(),
        )
    )
    db.commit()
    metric(
        "worker",
        job.region,
        "ChecksPersisted",
        job_id=str(job.id),
        monitor_id=str(job.monitor_id),
        outcome=observation.outcome,
        total_ms=observation.total_ms,
        error_category=observation.error_category,
    )
    return True


def fail_job(db: Session, claim: Claim, settings: Settings, now: datetime | None = None) -> None:
    now = now or utcnow()
    job = db.scalar(select(CheckJob).where(CheckJob.id == claim.job_id).with_for_update())
    if job is None or job.state != "RUNNING" or job.lease_token != claim.lease_token:
        db.rollback()
        return
    job.state = (
        "DEAD"
        if job.attempts >= settings.max_job_attempts
        else ("PUBLISH_PENDING" if settings.queue_backend == "sqs" else "RETRY")
    )
    job.available_at = now + timedelta(seconds=backoff(job.attempts))
    job.last_error, job.lease_token, job.lease_until = "WORKER_INTERNAL", None, None
    db.commit()


def reconcile_leases(db: Session, settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    jobs = list(
        db.scalars(
            select(CheckJob)
            .where(
                CheckJob.state == "RUNNING",
                CheckJob.lease_until <= now,
            )
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        job.state = (
            "DEAD"
            if job.attempts >= settings.max_job_attempts
            else ("PUBLISH_PENDING" if settings.queue_backend == "sqs" else "RETRY")
        )
        job.available_at = now + timedelta(seconds=backoff(job.attempts))
        job.last_error, job.lease_token, job.lease_until = "LEASE_EXPIRED", None, None
    db.commit()
    # Do not leave abandoned queued messages permanently blocking new slots.
    # CAS prevents overwriting a concurrently completed job. No target result is fabricated.
    candidates = list(
        db.execute(
            select(CheckJob.id, CheckJob.scheduled_at, Monitor.interval_seconds)
            .join(Monitor, Monitor.id == CheckJob.monitor_id)
            .where(CheckJob.state.in_(ACTIVE))
            .order_by(CheckJob.scheduled_at)
            .limit(100)
        )
    )
    for job_id, scheduled, interval in candidates:
        if scheduled < now - timedelta(seconds=interval):
            db.execute(
                update(CheckJob)
                .where(CheckJob.id == job_id, CheckJob.state.in_(ACTIVE))
                .values(
                    state="CANCELLED", lease_token=None, lease_until=None, last_error="STALE_JOB"
                )
            )
    db.commit()
    return len(jobs)


def local_job_id(db: Session, region: str) -> uuid.UUID | None:
    return db.scalar(
        select(CheckJob.id)
        .where(
            CheckJob.region == region,
            CheckJob.state.in_(("QUEUED", "RETRY")),
            CheckJob.available_at <= utcnow(),
        )
        .order_by(CheckJob.scheduled_at, CheckJob.id)
        .limit(1)
    )


def execute_job(
    session_factory,
    job_id: uuid.UUID,
    region: str,
    settings: Settings,
    checker: HTTPChecker | None = None,
) -> str:
    with session_factory() as db:
        action, claim = claim_job(db, job_id, region, settings)
    if claim is None:
        return action
    started = utcnow()
    try:
        observation = (checker or HTTPChecker()).check(
            claim.target_url, claim.timeout, claim.expected_min, claim.expected_max, claim.slow_ms
        )
        with session_factory() as db:
            finish_job(db, claim, observation, started)
    except Exception as exc:
        metric("worker", region, "ServiceErrors", error_type=type(exc).__name__)
        # Do not turn a worker/database bug into evidence that a website is DOWN.
        with session_factory() as db:
            fail_job(db, claim, settings)
        return "retry"
    return "ack"


def heartbeat(db: Session, identity: str, role: str, region: str) -> None:
    item = db.get(ServiceHeartbeat, identity)
    if item is None:
        db.add(ServiceHeartbeat(id=identity, role=role, region=region, seen_at=utcnow()))
    else:
        item.seen_at = utcnow()
    db.commit()


def prune(db: Session, settings: Settings) -> int:
    cutoff = utcnow() - timedelta(days=settings.check_retention_days)
    deleted = db.execute(
        delete(CheckJob).where(CheckJob.state.in_(TERMINAL), CheckJob.scheduled_at < cutoff)
    ).rowcount
    db.execute(
        delete(ServiceHeartbeat).where(ServiceHeartbeat.seen_at < utcnow() - timedelta(days=7))
    )
    db.commit()
    return deleted

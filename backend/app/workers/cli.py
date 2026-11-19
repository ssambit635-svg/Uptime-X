"""Separate scheduler/worker/operator entry points. Never run inside the API process.

python -m app.workers.cli scheduler --loop
python -m app.workers.cli worker --loop
python -m app.workers.cli dead-jobs
python -m app.workers.cli replay --job-id UUID --confirm
"""

import argparse
import json
import logging
import os
import signal
import socket
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.telemetry import metric
from app.models.entities import CheckJob, Monitor, ServiceHeartbeat, utcnow
from app.services.jobs import (
    enqueue_monitor,
    execute_job,
    heartbeat,
    local_job_id,
    prune,
    reconcile_leases,
    schedule_due,
)
from app.services.queue import SQSQueue, publish_outbox

logging.basicConfig(level=logging.INFO, format="%(message)s")


def replay_job(db, job_id, settings):
    original = db.get(CheckJob, job_id)
    if original is None or original.state != "DEAD":
        raise ValueError("Only a known dead job can be replayed")
    monitor = db.scalar(select(Monitor).where(Monitor.id == original.monitor_id).with_for_update())
    if monitor is None or monitor.is_paused:
        raise ValueError("Monitor is missing or paused")
    # New job/time/current policy. Never backfill a fabricated historic observation.
    jobs = enqueue_monitor(db, monitor, settings, utcnow())
    db.commit()
    metric("operator", original.region, "JobsReplayed", original_job_id=str(job_id))
    return [str(job.id) for job in jobs]


def service_identity(role: str, region: str) -> str:
    # The probe runs in the same container/hostname, not another healthy task.
    return f"{role}:{region}:{socket.gethostname()}"


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["scheduler", "worker", "health", "prune", "dead-jobs", "replay"]
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--role", choices=["worker", "scheduler"], default="worker")
    parser.add_argument("--job-id", type=uuid.UUID)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    region = settings.worker_region
    if settings.queue_backend == "sqs" and os.environ.get("AWS_REGION") != region:
        raise SystemExit(
            "AWS_REGION must match the deployed worker region; "
            "local processes cannot claim AWS attribution"
        )
    if args.command == "health":
        with SessionLocal() as db:
            recent = db.scalar(
                select(ServiceHeartbeat.id)
                .where(
                    ServiceHeartbeat.id == service_identity(args.role, region),
                    ServiceHeartbeat.seen_at
                    >= utcnow() - timedelta(seconds=180 if args.role == "scheduler" else 90),
                )
                .limit(1)
            )
        raise SystemExit(0 if recent else 1)
    if args.command in {"prune", "dead-jobs", "replay"}:
        with SessionLocal() as db:
            if args.command == "prune":
                print(json.dumps({"deleted_jobs": prune(db, settings)}))
            elif args.command == "dead-jobs":
                items = db.scalars(select(CheckJob).where(CheckJob.state == "DEAD").limit(100))
                print(
                    json.dumps(
                        [
                            {
                                "id": str(job.id),
                                "region": job.region,
                                "attempts": job.attempts,
                                "error": job.last_error,
                            }
                            for job in items
                        ]
                    )
                )
            else:
                if not args.confirm or not args.job_id:
                    raise SystemExit(
                        "Replay requires --job-id and --confirm; "
                        "review DLQ and current monitor policy first"
                    )
                print(json.dumps({"job_ids": replay_job(db, args.job_id, settings)}))
        return
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    identity = service_identity(args.command, region)
    queue = (
        SQSQueue(settings, region, long_poll=True)
        if args.command == "worker" and settings.queue_backend == "sqs"
        else None
    )
    last_prune = 0.0
    while running:
        try:
            with SessionLocal() as db:
                heartbeat(db, identity, args.command, region)
            metric(args.command, region, "Heartbeat")
            if args.command == "scheduler":
                with SessionLocal() as db:
                    reconcile_leases(db, settings)
                    scheduled = schedule_due(db, settings)
                published = (
                    publish_outbox(SessionLocal, settings) if settings.queue_backend == "sqs" else 0
                )
                metric("scheduler", region, "JobsScheduled", scheduled, published=published)
                with SessionLocal() as db:
                    oldest = db.scalar(
                        select(func.min(CheckJob.scheduled_at)).where(
                            CheckJob.state == "PUBLISH_PENDING"
                        )
                    )
                    dead = (
                        db.scalar(
                            select(func.count())
                            .select_from(CheckJob)
                            .where(CheckJob.state == "DEAD")
                        )
                        or 0
                    )
                    if args.loop and time.monotonic() - last_prune > 3600:
                        prune(db, settings)
                        last_prune = time.monotonic()
                metric(
                    "scheduler",
                    region,
                    "OutboxAgeSeconds",
                    max(0, (utcnow() - oldest).total_seconds()) if oldest else 0,
                    unit="Seconds",
                )
                metric("scheduler", region, "DeadJobs", dead)
            elif queue:
                delivery = queue.receive()
                if delivery:
                    action = (
                        execute_job(SessionLocal, delivery.job_id, region, settings)
                        if delivery.job_id
                        else "retry"
                    )
                    if action == "ack":
                        queue.acknowledge(delivery)
                    else:
                        queue.retry(delivery)
                    metric(
                        "worker",
                        region,
                        "Deliveries",
                        action=action,
                        poison=delivery.job_id is None,
                    )
            else:
                with SessionLocal() as db:
                    job_id = local_job_id(db, region)
                if job_id:
                    action = execute_job(SessionLocal, job_id, region, settings)
                    metric("worker", region, "Deliveries", job_id=str(job_id), action=action)
        except Exception as exc:
            # Never log DSNs, target URLs/queries, message bodies or credentials.
            metric(args.command, region, "ServiceErrors", error_type=type(exc).__name__)
            if not args.loop:
                raise SystemExit(1) from None
            time.sleep(3)
        if not args.loop:
            break
        time.sleep(5 if args.command == "scheduler" else 1)


if __name__ == "__main__":
    run()

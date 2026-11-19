import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.models.entities import CheckJob, MonitorCheck, ServiceHeartbeat, utcnow
from app.services.checker import Observation
from app.services.jobs import (
    backoff,
    claim_job,
    enqueue_monitor,
    execute_job,
    fail_job,
    finish_job,
    heartbeat,
    invalidate_jobs,
    local_job_id,
    prune,
    reconcile_leases,
    schedule_due,
)
from app.workers.cli import replay_job


def test_scheduler_is_due_only_and_does_not_catch_up_or_duplicate(db, monitor, settings):
    assert schedule_due(db, settings) == 1
    assert schedule_due(db, settings) == 0
    job = db.scalar(select(CheckJob))
    assert job.region == "local" and job.state == "QUEUED"
    assert monitor.next_check_at > utcnow()
    assert enqueue_monitor(db, monitor, settings, utcnow())[0].id == job.id
    monitor.next_check_at = utcnow() - timedelta(days=1)
    db.commit()
    assert schedule_due(db, settings) == 0
    assert db.scalar(select(func.count()).select_from(CheckJob)) == 1


def test_disabled_and_paused_monitors_do_not_enqueue(db, monitor, settings):
    settings.monitoring_enabled = False
    assert schedule_due(db, settings) == 0
    assert enqueue_monitor(db, monitor, settings, utcnow()) == []
    settings.monitoring_enabled = True
    monitor.is_paused = True
    assert schedule_due(db, settings) == 0


def test_controlled_network_check_persists_once_and_acknowledges_duplicates(
    db, monitor, settings, session_factory, public_http
):
    checker, _ = public_http
    schedule_due(db, settings)
    job_id = local_job_id(db, "local")
    db.rollback()
    assert execute_job(session_factory, job_id, "local", settings, checker) == "ack"
    assert execute_job(session_factory, job_id, "local", settings, checker) == "ack"
    db.expire_all()
    results = list(db.scalars(select(MonitorCheck)))
    assert len(results) == 1 and results[0].outcome == "UP"
    assert results[0].job_id == job_id and results[0].http_status == 200
    assert db.get(CheckJob, job_id).state == "COMPLETE"


def test_only_one_lease_can_execute_and_completion_is_fenced(db, monitor, settings):
    schedule_due(db, settings)
    job = db.scalar(select(CheckJob))
    action, first = claim_job(db, job.id, "local", settings)
    assert action == "execute"
    assert claim_job(db, job.id, "local", settings) == ("retry", None)
    expired = utcnow() - timedelta(seconds=1)
    job.lease_until = expired
    db.commit()
    assert finish_job(db, first, Observation(outcome="UP"), utcnow()) is False
    assert reconcile_leases(db, settings) == 1
    job.available_at = expired
    db.commit()
    _, second = claim_job(db, job.id, "local", settings)
    assert second and first.lease_token != second.lease_token
    assert finish_job(db, first, Observation(outcome="UP"), utcnow()) is False
    assert finish_job(db, second, Observation(outcome="UP"), utcnow()) is True
    assert finish_job(db, second, Observation(outcome="UP"), utcnow()) is False
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 1


@pytest.mark.parametrize("change", ["pause", "edit", "delete"])
def test_inflight_result_is_discarded_after_monitor_changes(db, monitor, settings, change):
    schedule_due(db, settings)
    job = db.scalar(select(CheckJob))
    _, claim = claim_job(db, job.id, "local", settings)
    if change == "delete":
        db.delete(monitor)
    else:
        invalidate_jobs(db, monitor)
        monitor.is_paused = change == "pause"
    db.commit()
    assert finish_job(db, claim, Observation(outcome="UP"), utcnow()) is False
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0


def test_stale_jobs_are_not_executed_or_backfilled(db, monitor, settings):
    job = enqueue_monitor(db, monitor, settings, utcnow() - timedelta(seconds=301))[0]
    db.commit()
    assert claim_job(db, job.id, "local", settings) == ("ack", None)
    assert db.get(CheckJob, job.id).state == "CANCELLED"
    assert claim_job(db, uuid.uuid4(), "local", settings) == ("ack", None)


def test_misrouted_messages_and_delayed_jobs_are_not_acknowledged(db, monitor, settings):
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    db.commit()
    assert claim_job(db, job.id, "other-region", settings) == ("retry", None)
    job.available_at = utcnow() + timedelta(seconds=30)
    db.commit()
    assert claim_job(db, job.id, "local", settings) == ("retry", None)


def test_infrastructure_failure_retries_then_dead_letters_without_target_failure(
    db, monitor, settings, session_factory
):
    settings.max_job_attempts = 2
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    db.commit()
    checker = Mock()
    checker.check.side_effect = RuntimeError("must not be stored")
    assert execute_job(session_factory, job.id, "local", settings, checker) == "retry"
    db.expire_all()
    job = db.get(CheckJob, job.id)
    assert job.state == "RETRY" and job.attempts == 1 and job.last_error == "WORKER_INTERNAL"
    job.available_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert execute_job(session_factory, job.id, "local", settings, checker) == "retry"
    db.expire_all()
    assert db.get(CheckJob, job.id).state == "DEAD"
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0
    assert claim_job(db, job.id, "local", settings) == ("retry", None)
    fresh_ids = replay_job(db, job.id, settings)
    assert len(fresh_ids) == 1 and fresh_ids[0] != str(job.id)
    fresh = db.get(CheckJob, uuid.UUID(fresh_ids[0]))
    assert fresh.scheduled_at > job.scheduled_at and fresh.revision == monitor.revision
    assert db.get(CheckJob, job.id).state == "DEAD"


def test_attempts_exhaustion_and_lease_expiry_are_bounded(db, monitor, settings):
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    job.attempts = settings.max_job_attempts
    db.commit()
    assert claim_job(db, job.id, "local", settings) == ("retry", None)
    assert job.state == "DEAD"
    job.state, job.lease_until = "RUNNING", utcnow() - timedelta(seconds=1)
    db.commit()
    assert reconcile_leases(db, settings) == 1
    assert job.state == "DEAD"
    assert 2 <= backoff(1) <= 5 and 256 <= backoff(100) <= 303


def test_stale_failure_handler_cannot_overwrite_a_new_lease(db, monitor, settings):
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    db.commit()
    _, claim = claim_job(db, job.id, "local", settings)
    job.lease_token = uuid.uuid4()
    db.commit()
    fail_job(db, claim, settings)
    assert job.state == "RUNNING"


def test_retention_prunes_history_and_heartbeats_not_active_jobs(db, monitor, settings, record):
    old = record(monitor, age=91 * 86400)
    active = enqueue_monitor(db, monitor, settings, utcnow())[0]
    db.add(
        ServiceHeartbeat(
            id="old", role="worker", region="local", seen_at=utcnow() - timedelta(days=8)
        )
    )
    db.commit()
    assert prune(db, settings) == 1
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0
    assert db.get(CheckJob, active.id) is not None
    heartbeat(db, "current", "worker", "local")
    heartbeat(db, "current", "worker", "local")
    assert db.scalar(select(func.count()).select_from(ServiceHeartbeat)) == 1
    assert old.job_id != active.id


def test_replay_requires_a_dead_job_and_active_monitor(db, monitor, settings):
    with pytest.raises(ValueError):
        replay_job(db, uuid.uuid4(), settings)
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    db.commit()
    with pytest.raises(ValueError):
        replay_job(db, job.id, settings)
    job.state, monitor.is_paused = "DEAD", True
    db.commit()
    with pytest.raises(ValueError):
        replay_job(db, job.id, settings)

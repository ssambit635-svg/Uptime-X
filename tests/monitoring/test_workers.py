import json
import sys
import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.models.entities import CheckJob, MonitorCheck, ServiceHeartbeat, utcnow
from app.services.checker import Observation
from app.services.jobs import enqueue_monitor, reconcile_leases
from app.services.queue import Delivery
from app.workers import cli


@pytest.fixture
def invoke(monkeypatch, settings, session_factory):
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli.signal, "signal", lambda *_: None)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["uptimex", *args])
        return cli.run()

    return run


def test_scheduler_and_local_worker_execute_in_separate_process_entrypoints(
    invoke, monkeypatch, db, monitor
):
    invoke("scheduler")
    job = db.scalar(select(CheckJob))
    checker = Mock()
    checker.check.return_value = Observation(outcome="UP", http_status=200, total_ms=13)
    monkeypatch.setattr("app.services.jobs.HTTPChecker", lambda: checker)
    invoke("worker")
    db.expire_all()
    assert db.get(CheckJob, job.id).state == "COMPLETE"
    assert db.scalar(select(MonitorCheck)).total_ms == 13
    invoke("worker")  # An idle worker is healthy, not an exception.
    for role in ("scheduler", "worker"):
        with pytest.raises(SystemExit) as result:
            invoke("health", "--role", role)
        assert result.value.code == 0


def test_health_does_not_mask_this_task_with_another_workers_heartbeat(invoke, db):
    db.add(ServiceHeartbeat(id="another-task", role="worker", region="local", seen_at=utcnow()))
    db.commit()
    with pytest.raises(SystemExit) as result:
        invoke("health")
    assert result.value.code == 1


def test_operators_prune_inspect_and_explicitly_replay(invoke, db, monitor, settings, capsys):
    job = enqueue_monitor(db, monitor, settings, utcnow())[0]
    job.state, job.attempts, job.last_error = "DEAD", 5, "WORKER_INTERNAL"
    db.commit()
    invoke("dead-jobs")
    assert json.loads(capsys.readouterr().out)[0]["id"] == str(job.id)
    with pytest.raises(SystemExit, match="requires --job-id and --confirm"):
        invoke("replay", "--job-id", str(job.id))
    invoke("replay", "--job-id", str(job.id), "--confirm")
    ids = json.loads(capsys.readouterr().out)["job_ids"]
    assert len(ids) == 1 and ids[0] != str(job.id)
    invoke("prune")
    assert json.loads(capsys.readouterr().out) == {"deleted_jobs": 0}


@pytest.mark.parametrize("action,poison", [("ack", False), ("retry", False), ("retry", True)])
def test_sqs_worker_acknowledges_only_completed_valid_deliveries(
    invoke, settings, monkeypatch, action, poison
):
    settings.queue_backend = "sqs"
    settings.worker_region = "ap-south-1"
    monkeypatch.setenv("AWS_REGION", settings.worker_region)
    queue = Mock()
    delivery = Delivery("opaque-receipt", None if poison else uuid.uuid4(), 1)
    queue.receive.return_value = delivery
    monkeypatch.setattr(cli, "SQSQueue", lambda *_, **__: queue)
    executor = Mock(return_value=action)
    monkeypatch.setattr(cli, "execute_job", executor)
    invoke("worker")
    if action == "ack":
        queue.acknowledge.assert_called_once_with(delivery)
        queue.retry.assert_not_called()
    else:
        queue.retry.assert_called_once_with(delivery)
        queue.acknowledge.assert_not_called()
    assert executor.call_count == (0 if poison else 1)
    queue.receive.return_value = None
    invoke("worker")


def test_cloud_process_cannot_claim_a_different_aws_region(invoke, settings, monkeypatch):
    settings.queue_backend = "sqs"
    settings.worker_region = "ap-south-1"
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    with pytest.raises(SystemExit, match="must match"):
        invoke("worker")


def test_loop_stops_on_signal_and_prunes_periodically(invoke, monkeypatch):
    handlers = {}
    monkeypatch.setattr(cli.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(cli.time, "sleep", lambda _: handlers[cli.signal.SIGTERM]())
    invoke("scheduler", "--loop")


def test_internal_errors_are_sanitized_and_fail_one_off_task(invoke, monkeypatch):
    monkeypatch.setattr(cli, "schedule_due", Mock(side_effect=RuntimeError("private://secret")))
    metric = Mock()
    monkeypatch.setattr(cli, "metric", metric)
    with pytest.raises(SystemExit) as result:
        invoke("scheduler")
    assert result.value.code == 1
    assert metric.call_args.kwargs == {"error_type": "RuntimeError"}
    assert "private" not in str(metric.call_args)


def test_scheduler_publishes_outbox_with_sqs(invoke, settings, monkeypatch):
    settings.queue_backend = "sqs"
    settings.worker_region = "ap-south-1"
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    publisher = Mock(return_value=3)
    monkeypatch.setattr(cli, "publish_outbox", publisher)
    invoke("scheduler")
    publisher.assert_called_once()


def test_reconciliation_unblocks_old_abandoned_messages_without_fabricating_data(
    db, monitor, settings
):
    job = enqueue_monitor(db, monitor, settings, utcnow() - timedelta(seconds=301))[0]
    db.commit()
    reconcile_leases(db, settings)
    assert db.get(CheckJob, job.id).state == "CANCELLED"
    assert db.scalar(select(MonitorCheck)) is None
    assert len(enqueue_monitor(db, monitor, settings, utcnow())) == 1

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select

from app.models.entities import CheckJob, Monitor, MonitorCheck, utcnow
from app.services.checker import Observation
from app.services.jobs import (
    claim_job,
    finish_job,
    invalidate_jobs,
    schedule_due,
)


@pytest.fixture(autouse=True)
def postgres_only(db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("Distributed row-lock concurrency requires PostgreSQL")


def test_parallel_schedulers_only_create_one_regional_slot(db, monitor, settings, session_factory):
    barrier = Barrier(2)
    now = utcnow()

    def schedule():
        with session_factory() as session:
            barrier.wait(timeout=5)
            return schedule_due(session, settings, now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: schedule(), range(2))) == [0, 1]
    assert db.scalar(select(func.count()).select_from(CheckJob)) == 1


def test_parallel_duplicate_deliveries_receive_one_execution_lease(
    db, monitor, settings, session_factory
):
    schedule_due(db, settings)
    job_id = db.scalar(select(CheckJob.id))
    db.rollback()
    barrier = Barrier(6)

    def claim():
        with session_factory() as session:
            barrier.wait(timeout=5)
            return claim_job(session, job_id, "local", settings)

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: claim(), range(6)))
    assert sum(action == "execute" for action, _ in results) == 1
    assert sum(action == "retry" for action, _ in results) == 5
    assert db.get(CheckJob, job_id).attempts == 1
    winning_claim = next(claim for _, claim in results if claim)
    assert finish_job(db, winning_claim, Observation(outcome="UP", http_status=200), utcnow())
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 1


def test_pause_fences_a_concurrent_worker_result(db, monitor, settings, session_factory):
    schedule_due(db, settings)
    job_id = db.scalar(select(CheckJob.id))
    _, claim = claim_job(db, job_id, "local", settings)
    db.scalar(select(Monitor).where(Monitor.id == monitor.id).with_for_update())
    started = Event()

    def finish():
        with session_factory() as session:
            started.set()
            return finish_job(session, claim, Observation(outcome="UP"), utcnow())

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(finish)
        assert started.wait(timeout=5)
        invalidate_jobs(db, monitor)
        monitor.is_paused = True
        db.commit()
        assert result.result(timeout=5) is False
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0

"""Exercise upgrade/backfill/destructive rollback with populated disposable data.

Run from the repository root with APP_ENV=test, PYTHONPATH=backend, and DATABASE_URL
pointing to an EMPTY *_test PostgreSQL DB or *_test.db SQLite file (.local/ci.db
is also accepted for CI). Leaves an empty head schema, never fetches a target.
"""

import os
import uuid
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import make_engine
from app.models.entities import CheckJob, Monitor, MonitorCheck, ServiceHeartbeat, utcnow

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ("users", "auth_sessions", "monitors")
MONITORING = {"check_jobs", "monitor_checks", "service_heartbeats"}


def run() -> None:
    url = os.environ["DATABASE_URL"]
    parsed = make_url(url)
    if os.environ.get("APP_ENV") != "test":
        raise SystemExit("Migration smoke requires APP_ENV=test and an empty disposable database")
    if parsed.get_backend_name() == "sqlite":
        path = Path(parsed.database or "").resolve()
        safe = path.name.endswith("_test.db") or path == ROOT / ".local" / "ci.db"
    else:
        safe = parsed.get_backend_name() == "postgresql" and bool(
            parsed.database and parsed.database.endswith("_test")
        )
    if not safe:
        raise SystemExit("Migration smoke requires a disposable *_test database or *_test.db file")
    engine = make_engine(url)
    try:
        if set(sa.inspect(engine).get_table_names()) - {"alembic_version"}:
            raise SystemExit(
                "Refusing migration smoke: database already contains application tables"
            )
        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, "0001")
        metadata = sa.MetaData()
        metadata.reflect(bind=engine, only=FOUNDATION)
        user_id = uuid.uuid4()
        monitor_ids = [uuid.uuid4(), uuid.uuid4()]
        now = utcnow()

        def identifier(value):
            return value.hex if engine.dialect.name == "sqlite" else value

        with engine.begin() as connection:
            connection.execute(
                metadata.tables["users"].insert(),
                {
                    "id": identifier(user_id),
                    "email": "migration-fixture@example.invalid",
                    "password_hash": "test-only-not-a-login-hash",
                    "created_at": now,
                },
            )
            connection.execute(
                metadata.tables["auth_sessions"].insert(),
                {
                    "token_digest": "0" * 64,
                    "user_id": identifier(user_id),
                    "created_at": now,
                    "expires_at": now + timedelta(hours=1),
                },
            )
            connection.execute(
                metadata.tables["monitors"].insert(),
                [
                    {
                        "id": identifier(monitor_id),
                        "user_id": identifier(user_id),
                        "name": f"Migration fixture {index}",
                        "target_url": f"https://example.invalid/health/{index}",
                        "target_fingerprint": str(index) * 64,
                        "interval_seconds": 300 + index * 300,
                        "timeout_seconds": 10,
                        "is_paused": bool(index),
                        "created_at": now,
                        "updated_at": now,
                    }
                    for index, monitor_id in enumerate(monitor_ids)
                ],
            )

        def foundation_snapshot():
            with engine.connect() as connection:
                return {
                    name: list(
                        connection.execute(
                            sa.select(metadata.tables[name]).order_by(
                                *metadata.tables[name].primary_key.columns
                            )
                        ).mappings()
                    )
                    for name in FOUNDATION
                }

        baseline = foundation_snapshot()
        command.upgrade(config, "head")
        command.check(config)
        assert foundation_snapshot() == baseline, "Upgrade changed foundation data"
        with Session(engine) as db:
            for monitor_id in monitor_ids:
                monitor = db.get(Monitor, monitor_id)
                assert monitor is not None
                assert monitor.regions == ["local"] and monitor.revision == 1
                assert monitor.expected_status_min == 200 and monitor.expected_status_max == 299
                assert monitor.failure_threshold == 3 and monitor.recovery_threshold == 2
                assert monitor.next_check_at and monitor.revision_started_at

        def add_monitoring_fixture():
            with Session(engine) as db:
                job = CheckJob(
                    monitor_id=monitor_ids[0],
                    region="local",
                    revision=1,
                    scheduled_at=now,
                    state="COMPLETE",
                )
                db.add(job)
                db.flush()
                db.add(
                    MonitorCheck(
                        job_id=job.id,
                        monitor_id=monitor_ids[0],
                        revision=1,
                        region="local",
                        scheduled_at=now,
                        started_at=now,
                        checked_at=now,
                        outcome="UP",
                        http_status=200,
                        total_ms=1,
                        response_bytes=0,
                        redirect_count=0,
                    )
                )
                db.add(
                    ServiceHeartbeat(
                        id="migration-fixture", role="worker", region="local", seen_at=now
                    )
                )
                db.commit()

        add_monitoring_fixture()
        command.downgrade(config, "0001")
        assert not MONITORING.intersection(sa.inspect(engine).get_table_names())
        assert foundation_snapshot() == baseline, "Monitoring rollback changed foundation data"
        command.upgrade(config, "head")
        command.check(config)
        assert foundation_snapshot() == baseline, "Re-upgrade changed foundation data"
        add_monitoring_fixture()
        # SQLite batch recreation must preserve FK cascades as well as row values.
        with engine.begin() as connection:
            connection.execute(
                metadata.tables["users"]
                .delete()
                .where(metadata.tables["users"].c.id == identifier(user_id))
            )
            for table in (*FOUNDATION, "check_jobs", "monitor_checks"):
                assert connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"')) == 0
        command.downgrade(config, "base")
        assert set(sa.inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")
        command.check(config)
        print("Populated migration upgrade/backfill/rollback/re-upgrade/cascades: PASS")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()

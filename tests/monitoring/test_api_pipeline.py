from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models.entities import CheckJob, MonitorCheck, ServiceHeartbeat, utcnow
from app.services.jobs import execute_job, schedule_due

PASSWORD = "monitoring-test-only-password"

BASE = "/api/v1/monitors"


def test_add_schedule_execute_observe_history_analytics_and_pause(
    authed, db, settings, session_factory, public_http, public_dns
):
    checker, _ = public_http
    created = authed.post(
        BASE, json={"name": "Observed website", "target_url": "http://health.example.com/ok"}
    )
    assert created.status_code == 201
    item = created.json()
    path = f"{BASE}/{item['id']}"
    assert item["status"] == "UNKNOWN"
    assert authed.get(path + "/analytics").json()["eligible_checks"] == 0
    assert authed.get(path + "/checks").json()["items"] == []
    assert schedule_due(db, settings) == 1
    job_id = db.scalar(select(CheckJob.id))
    assert execute_job(session_factory, job_id, "local", settings, checker) == "ack"
    db.expire_all()
    observed = authed.get(path).json()
    assert observed["status"] == "UP" and observed["availability_percent"] == 100
    assert observed["last_checked_at"] and observed["response_time_ms"] > 0
    checks = authed.get(path + "/checks").json()
    assert checks["total"] == 1 and checks["items"][0]["provenance"] == "REAL"
    assert checks["items"][0]["response_bytes"] == 7 and "body" not in checks["items"][0]
    assert authed.get(path + "/analytics").json()["availability_percent"] == 100
    assert authed.post(path + "/pause").json()["status"] == "PAUSED"
    assert authed.get(path + "/checks").json()["total"] == 1  # Pause preserves history.
    assert authed.post(path + "/resume").json()["status"] == "UNKNOWN"
    assert authed.delete(path).status_code == 204
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0


def test_check_now_is_owned_persistently_rate_limited_and_never_executes_in_api(
    authed, db, public_dns
):
    item = authed.post(BASE, json={"name": "Queued", "target_url": "https://example.com"}).json()
    path = f"{BASE}/{item['id']}"
    assert authed.post(path + "/check").status_code == 202
    assert db.scalar(select(func.count()).select_from(CheckJob)) == 1
    assert db.scalar(select(func.count()).select_from(MonitorCheck)) == 0
    retry = authed.post(path + "/check")
    assert retry.status_code == 429 and retry.headers["Retry-After"] == "60"
    authed.post(path + "/pause")
    assert authed.post(path + "/check").status_code == 409
    assert authed.get(path + "/checks?limit=201").status_code == 422
    assert authed.get(path + "/analytics?window=365d").status_code == 422
    assert authed.get(path + "/checks?region=invalid").status_code == 422
    assert authed.get(path + "/analytics?region=invalid").status_code == 422


def test_history_analytics_check_now_and_operations_do_not_leak_tenants(
    authed, app, db, public_dns
):
    item = authed.post(BASE, json={"name": "Private", "target_url": "https://example.com"}).json()
    path = f"{BASE}/{item['id']}"
    authed.post(path + "/check")
    with TestClient(app, headers={"X-UptimeX-Client": "web"}) as other:
        other.post(
            "/api/v1/auth/register",
            json={"email": "metrics-other@example.com", "password": PASSWORD},
        )
        assert other.get(path + "/checks").status_code == 404
        assert other.get(path + "/analytics").status_code == 404
        assert other.post(path + "/check").status_code == 404
        assert other.get("/api/v1/operations").json()["jobs"]["pending"] == 0
    assert authed.get("/api/v1/operations").json()["jobs"]["pending"] == 1


def test_configuration_policy_validation_and_region_attribution(authed, public_dns):
    invalid = [
        {"expected_status_min": 500, "expected_status_max": 200},
        {"regions": ["ap-south-1"]},
        {"regions": ["local", "local"]},
        {"failure_threshold": 0},
        {"expected_status_max": 600},
        {"slow_threshold_ms": 0},
        {"regions": []},
    ]
    for fields in invalid:
        assert (
            authed.post(
                BASE, json={"name": "Policy", "target_url": "https://example.com", **fields}
            ).status_code
            == 422
        )
    item = authed.post(
        BASE,
        json={
            "name": "Policy",
            "target_url": "https://example.com",
            "expected_status_min": 300,
            "expected_status_max": 399,
        },
    ).json()
    path = f"{BASE}/{item['id']}"
    assert authed.patch(path, json={"expected_status_min": 500}).status_code == 422
    assert authed.patch(path, json={"regions": ["ap-south-1"]}).status_code == 422
    updated = authed.patch(path, json={"timeout_seconds": 5}).json()
    assert updated["revision"] == item["revision"] + 1
    assert (
        authed.patch(path, json={"name": "Rename only"}).json()["revision"] == updated["revision"]
    )


def test_worker_and_scheduler_health_is_observed_not_assumed(authed, db):
    initial = authed.get("/api/v1/operations").json()
    assert initial["scheduler"]["healthy"] is False
    assert initial["regions"][0]["healthy_workers"] == 0
    db.add_all(
        [
            ServiceHeartbeat(id="worker-new", role="worker", region="local", seen_at=utcnow()),
            ServiceHeartbeat(
                id="worker-old",
                role="worker",
                region="local",
                seen_at=utcnow() - timedelta(seconds=91),
            ),
            ServiceHeartbeat(id="scheduler", role="scheduler", region="local", seen_at=utcnow()),
        ]
    )
    db.commit()
    data = authed.get("/api/v1/operations").json()
    assert data["scheduler"]["healthy"] and data["regions"][0]["healthy_workers"] == 1
    assert data["configured_regions"] == ["local"] and "queue_url" not in data

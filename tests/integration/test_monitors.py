import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import PASSWORD

BASE = "/api/v1/monitors"


def create(client: TestClient, **overrides):
    return client.post(
        BASE, json={"name": "Production", "target_url": "https://example.com", **overrides}
    )


@pytest.fixture(autouse=True)
def dns(public_dns):
    pass


def test_create_never_invents_measurements(authed: TestClient):
    result = create(authed)
    assert result.status_code == 201
    data = result.json()
    assert data["target_url"] == "https://example.com/"
    assert data["status"] == "UNKNOWN"
    assert data["provenance"] == "REAL"
    assert data["interval_seconds"] == 300
    assert data["timeout_seconds"] == 10
    assert data["last_checked_at"] is None
    assert data["availability_percent"] is None
    assert data["response_time_ms"] is None
    assert data["created_at"].endswith("Z")
    listing = authed.get(BASE).json()
    assert listing["total"] == 1
    assert listing["quota"] == 10
    assert listing["checks_enabled"] is False
    assert listing["items"][0] == data


def test_edit_pause_resume_delete_lifecycle(authed: TestClient):
    monitor_id = create(authed).json()["id"]
    path = f"{BASE}/{monitor_id}"
    assert authed.get(path).status_code == 200
    result = authed.patch(path, json={"name": "  Marketing  ", "interval_seconds": 600})
    assert result.status_code == 200
    assert result.json()["name"] == "Marketing"
    assert result.json()["interval_seconds"] == 600
    for _ in range(2):
        assert authed.post(f"{path}/pause").json()["status"] == "PAUSED"
    for _ in range(2):
        assert authed.post(f"{path}/resume").json()["status"] == "UNKNOWN"
    assert authed.delete(path).status_code == 204
    assert authed.get(path).status_code == 404
    assert authed.get(BASE).json()["total"] == 0


def test_every_monitor_operation_is_tenant_scoped(authed: TestClient, app: FastAPI):
    owner_id = create(authed).json()["id"]
    with TestClient(app, headers={"X-UptimeX-Client": "web"}) as other:
        assert (
            other.post(
                "/api/v1/auth/register", json={"email": "other@example.com", "password": PASSWORD}
            ).status_code
            == 201
        )
        path = f"{BASE}/{owner_id}"
        assert other.get(BASE).json()["items"] == []
        for method, suffix, payload in [
            ("GET", "", None),
            ("PATCH", "", {"name": "stolen"}),
            ("POST", "/pause", None),
            ("POST", "/resume", None),
            ("DELETE", "", None),
        ]:
            response = other.request(method, path + suffix, json=payload)
            assert response.status_code == 404, (method, response.text)
        # Different owners may independently monitor the same URL.
        assert create(other).status_code == 201
    assert authed.get(f"{BASE}/{owner_id}").json()["name"] == "Production"


def test_duplicate_canonical_urls_are_rejected(authed: TestClient):
    assert create(authed).status_code == 201
    response = create(authed, target_url="https://EXAMPLE.com:443/")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_MONITOR"


def test_update_cannot_duplicate_another_monitor(authed: TestClient):
    create(authed)
    second = create(authed, target_url="https://example.org").json()["id"]
    response = authed.patch(f"{BASE}/{second}", json={"target_url": "https://example.com/"})
    assert response.status_code == 409
    assert authed.get(f"{BASE}/{second}").json()["target_url"] == "https://example.org/"


def test_quota_includes_paused_monitors_and_delete_frees_slot(authed: TestClient):
    ids = []
    for i in range(10):
        result = create(authed, target_url=f"https://example.com/{i}")
        assert result.status_code == 201
        ids.append(result.json()["id"])
    authed.post(f"{BASE}/{ids[0]}/pause")
    assert create(authed, target_url="https://example.com/overflow").status_code == 409
    authed.delete(f"{BASE}/{ids[0]}")
    assert create(authed, target_url="https://example.com/new").status_code == 201


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "  "},
        {"name": None},
        {"name": "x" * 121},
        {"interval_seconds": 60},
        {"interval_seconds": True},
        {"interval_seconds": "300"},
        {"interval_seconds": None},
        {"timeout_seconds": 11},
        {"timeout_seconds": 0},
        {"is_paused": True},
        {"user_id": str(uuid.uuid4())},
        {"status": "UP"},
    ],
)
def test_patch_validation(authed: TestClient, changes):
    monitor_id = create(authed).json()["id"]
    assert authed.patch(f"{BASE}/{monitor_id}", json=changes).status_code == 422


def test_url_policy_applies_on_create_and_edit(authed: TestClient):
    assert create(authed, target_url="http://127.0.0.1").status_code == 422
    assert create(authed, target_url="http://169.254.169.254/latest/meta-data").status_code == 422
    monitor_id = create(authed).json()["id"]
    response = authed.patch(f"{BASE}/{monitor_id}", json={"target_url": "http://10.0.0.1"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSAFE_TARGET"
    assert authed.get(f"{BASE}/{monitor_id}").json()["target_url"] == "https://example.com/"


def test_pagination_is_bounded(authed: TestClient):
    for i in range(3):
        create(authed, target_url=f"https://example.com/{i}")
    page = authed.get(BASE, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
        assert authed.get(BASE, params=params).status_code == 422


def test_monitors_require_authentication(client: TestClient):
    assert client.get(BASE).status_code == 401
    assert create(client).status_code == 401


def test_postgres_serializes_concurrent_quota_checks(authed, app, db_engine):
    from concurrent.futures import ThreadPoolExecutor

    if db_engine.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency guarantee requires PostgreSQL")
    for index in range(9):
        assert create(authed, target_url=f"https://example.com/seed/{index}").status_code == 201
    cookies = dict(authed.cookies)

    def attempt(index):
        with TestClient(app, headers={"X-UptimeX-Client": "web"}, cookies=cookies) as client:
            return create(client, target_url=f"https://example.com/concurrent/{index}").status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 3
    assert authed.get(BASE).json()["total"] == 10

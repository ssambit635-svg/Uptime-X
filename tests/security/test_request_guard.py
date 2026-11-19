import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import PASSWORD


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "https://[bad", ""])
def test_cross_origin_and_malformed_origins_rejected(client: TestClient, origin):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD},
        headers={"Origin": origin},
    )
    assert response.status_code == 403


def test_custom_header_required_even_without_origin(app: FastAPI):
    with TestClient(app) as browser:
        result = browser.post("/api/v1/auth/logout")
        assert result.status_code == 403


def test_same_origin_client_is_allowed(client: TestClient):
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code
        == 204
    )


def test_cross_site_fetch_rejected(client: TestClient):
    assert (
        client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )


def test_no_cors_permission_for_untrusted_preflight(client: TestClient):
    response = client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-UptimeX-Client",
        },
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_rejected_requests_also_have_request_ids_and_no_store(client):
    response = client.post("/api/v1/auth/logout", headers={"Origin": "null"})
    assert response.status_code == 403
    assert response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"


def test_unknown_routes_and_methods_have_consistent_errors(client):
    for response in (
        client.get("/api/v1/not-a-route"),
        client.put("/api/v1/health"),
    ):
        assert response.status_code in {404, 405}
        assert response.json()["error"]["code"] == "HTTP_ERROR"

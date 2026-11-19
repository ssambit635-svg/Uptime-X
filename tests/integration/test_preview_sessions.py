from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import PREVIEW_SESSION_HEADER, digest_token
from app.models.entities import AuthSession, utcnow
from conftest import PASSWORD

BASE = "/api/v1/auth"
MODE = {"X-UptimeX-Session-Mode": "preview"}


@pytest.fixture
def preview(app, monkeypatch):
    settings = Settings(embedded_preview=True, _env_file=None)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    with TestClient(
        app, base_url="https://testserver", headers={"X-UptimeX-Client": "web"}
    ) as client:
        yield client


def register(client, email="preview@example.com", *, opt_in=True):
    response = client.post(
        f"{BASE}/register",
        json={"email": email, "password": PASSWORD},
        headers=MODE if opt_in else {},
    )
    assert response.status_code == 201
    return response.json()


def test_cookie_blocked_preview_can_authenticate_and_use_monitors(preview, db: Session):
    payload = register(preview)
    credential = payload["preview_session"]
    token = credential["token"]
    expires = datetime.fromisoformat(credential["expires_at"].replace("Z", "+00:00"))
    assert timedelta(minutes=59) < expires - datetime.now(UTC) <= timedelta(minutes=60)
    assert db.get(AuthSession, digest_token(token)) is not None
    preview.cookies.clear()  # Reproduce a browser/proxy that never returns cookies.
    headers = {PREVIEW_SESSION_HEADER: token}
    me = preview.get(f"{BASE}/me", headers=headers)
    assert me.status_code == 200 and me.json()["id"] == payload["id"]
    assert "preview_session" not in me.json()
    result = preview.post(
        "/api/v1/monitors",
        json={"name": "Private workspace", "target_url": "https://8.8.8.8"},
        headers=headers,
    )
    assert result.status_code == 201
    assert preview.get("/api/v1/monitors", headers=headers).json()["total"] == 1


def test_preview_transport_requires_explicit_opt_in(preview):
    payload = register(preview, opt_in=False)
    assert "preview_session" not in payload


@pytest.mark.parametrize("environment", ["development", "production"])
def test_cookie_only_modes_never_issue_or_accept_preview_credentials(app, monkeypatch, environment):
    settings = Settings(
        app_env=environment,
        embedded_preview=False,
        session_cookie_secure=environment == "production",
        database_url="postgresql+psycopg://user@db/uptimex",
        _env_file=None,
    )
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    # The app fixture still injects its isolated test database, never this settings URL.
    with TestClient(
        app, base_url="https://testserver", headers={"X-UptimeX-Client": "web"}
    ) as client:
        payload = register(client)
        assert "preview_session" not in payload
        cookie = client.cookies[settings.cookie_name]
        client.cookies.clear()
        assert client.get(f"{BASE}/me", headers={PREVIEW_SESSION_HEADER: cookie}).status_code == 401
        assert (
            client.get(
                f"{BASE}/me", headers={"Cookie": f"{settings.cookie_name}={cookie}"}
            ).status_code
            == 200
        )


def test_preview_mode_headers_are_not_authentication(preview):
    assert preview.get(f"{BASE}/me", headers=MODE).status_code == 401
    assert (
        preview.get("/api/v1/monitors", headers={PREVIEW_SESSION_HEADER: "A" * 43}).status_code
        == 401
    )


def test_preview_logout_revokes_header_only_session(preview, db):
    token = register(preview)["preview_session"]["token"]
    preview.cookies.clear()
    headers = {PREVIEW_SESSION_HEADER: token}
    assert preview.post(f"{BASE}/logout", headers=headers).status_code == 204
    assert db.get(AuthSession, digest_token(token)) is None
    assert preview.get(f"{BASE}/me", headers=headers).status_code == 401


def test_preview_login_rotates_the_previous_header_session(preview, db):
    token = register(preview)["preview_session"]["token"]
    preview.cookies.clear()
    response = preview.post(
        f"{BASE}/login",
        json={"email": "preview@example.com", "password": PASSWORD},
        headers={**MODE, PREVIEW_SESSION_HEADER: token},
    )
    assert response.status_code == 200
    replacement = response.json()["preview_session"]["token"]
    assert replacement != token
    assert db.get(AuthSession, digest_token(token)) is None
    preview.cookies.clear()
    assert preview.get(f"{BASE}/me", headers={PREVIEW_SESSION_HEADER: token}).status_code == 401
    assert (
        preview.get(f"{BASE}/me", headers={PREVIEW_SESSION_HEADER: replacement}).status_code == 200
    )


def test_expired_preview_session_is_rejected_by_the_server(preview, db):
    token = register(preview)["preview_session"]["token"]
    session = db.get(AuthSession, digest_token(token))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    preview.cookies.clear()
    assert preview.get(f"{BASE}/me", headers={PREVIEW_SESSION_HEADER: token}).status_code == 401


def test_preview_token_does_not_relax_csrf_or_tenant_isolation(preview):
    first = register(preview, "owner-preview@example.com")
    owner_headers = {PREVIEW_SESSION_HEADER: first["preview_session"]["token"]}
    preview.cookies.clear()
    owned = preview.post(
        "/api/v1/monitors",
        headers=owner_headers,
        json={"name": "Owner only", "target_url": "https://8.8.8.8"},
    ).json()
    second = register(preview, "other-preview@example.com")
    other_headers = {PREVIEW_SESSION_HEADER: second["preview_session"]["token"]}
    preview.cookies.clear()
    assert preview.get(f"/api/v1/monitors/{owned['id']}", headers=other_headers).status_code == 404
    assert (
        preview.post(
            f"{BASE}/logout", headers={**owner_headers, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert preview.get(f"{BASE}/me", headers=owner_headers).status_code == 200

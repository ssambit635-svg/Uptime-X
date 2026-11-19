from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import digest_token
from app.models.entities import AuthSession, User, utcnow
from conftest import PASSWORD

BASE = "/api/v1/auth"


def test_register_persists_hash_and_revocable_cookie(client: TestClient, db: Session):
    response = client.post(
        f"{BASE}/register", json={"email": "Person@Example.com", "password": PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "person@example.com"
    assert set(response.json()) == {"id", "email", "created_at"}
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    user = db.scalar(select(User))
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    session = db.scalar(select(AuthSession))
    token = client.cookies[get_settings().cookie_name]
    assert session.token_digest == digest_token(token)
    assert token not in session.token_digest
    assert session.expires_at.tzinfo is not None
    assert client.get(f"{BASE}/me").json()["id"] == response.json()["id"]


def test_duplicate_email_is_case_insensitive(authed: TestClient):
    result = authed.post(
        f"{BASE}/register", json={"email": "OWNER@EXAMPLE.COM", "password": PASSWORD}
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "EMAIL_IN_USE"


def test_login_rotates_session_and_logout_revokes_it(authed: TestClient, db: Session):
    old = authed.cookies[get_settings().cookie_name]
    result = authed.post(f"{BASE}/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert result.status_code == 200
    new = authed.cookies[get_settings().cookie_name]
    assert new != old
    assert db.get(AuthSession, digest_token(old)) is None
    assert authed.post(f"{BASE}/logout").status_code == 204
    authed.cookies.set(get_settings().cookie_name, new)
    assert authed.get(f"{BASE}/me").status_code == 401
    assert db.get(AuthSession, digest_token(new)) is None


def test_expired_session_is_rejected(authed: TestClient, db: Session):
    session = db.scalar(select(AuthSession))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert authed.get(f"{BASE}/me").status_code == 401


def test_bad_credentials_do_not_reveal_account_existence(authed: TestClient):
    existing = authed.post(
        f"{BASE}/login", json={"email": "owner@example.com", "password": "wrong-password"}
    )
    missing = authed.post(
        f"{BASE}/login", json={"email": "missing@example.com", "password": "wrong-password"}
    )
    assert existing.status_code == missing.status_code == 401
    assert existing.json() == missing.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "owner@example.com", "password": "short"},
        {"email": "owner@example.com", "password": "x" * 129},
        {"email": "owner@example.com", "password": PASSWORD, "role": "admin"},
    ],
)
def test_invalid_credentials_never_echo_passwords(client: TestClient, payload):
    result = client.post(f"{BASE}/register", json=payload)
    assert result.status_code == 422
    assert payload["password"] not in result.text
    assert "input" not in result.json()["error"]


def test_unauthenticated_access_and_idempotent_logout(client: TestClient):
    assert client.get(f"{BASE}/me").status_code == 401
    assert client.post(f"{BASE}/logout").status_code == 204


def test_login_rate_limit(client: TestClient):
    for _ in range(20):
        assert (
            client.post(
                f"{BASE}/login", json={"email": "missing@example.com", "password": PASSWORD}
            ).status_code
            == 401
        )
    response = client.post(
        f"{BASE}/login", json={"email": "missing@example.com", "password": PASSWORD}
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_embedded_preview_uses_partitioned_secure_cookies(app, monkeypatch):
    from app.core.config import Settings

    settings = Settings(embedded_preview=True, _env_file=None)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    with TestClient(
        app, base_url="https://testserver", headers={"X-UptimeX-Client": "web"}
    ) as preview:
        response = preview.post(
            f"{BASE}/register", json={"email": "preview@example.com", "password": PASSWORD}
        )
        cookie = response.headers["set-cookie"]
        assert "__Host-uptimex_session=" in cookie
        assert "Secure" in cookie and "SameSite=none" in cookie and "Partitioned" in cookie
        assert preview.get(f"{BASE}/me").status_code == 200
        response = preview.post(f"{BASE}/logout")
        assert "Partitioned" in response.headers["set-cookie"]
        assert preview.get(f"{BASE}/me").status_code == 401

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import RateLimiter


def test_health_checks_database_and_reports_capability(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["database"] == "connected"
    assert response.json()["checks_enabled"] is False
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_production_requires_postgres_and_secure_cookies():
    with pytest.raises(ValidationError):
        Settings(app_env="production", session_cookie_secure=False, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            session_cookie_secure=True,
            database_url="sqlite://",
            _env_file=None,
        )
    settings = Settings(
        app_env="production",
        session_cookie_secure=True,
        database_url="postgresql+psycopg://user@db/uptimex",
        _env_file=None,
    )
    assert settings.cookie_name == "__Host-uptimex_session"


def test_rate_limiter_expiry_and_independent_scopes(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.core.security.time.monotonic", lambda: now[0])
    limiter = RateLimiter()
    limiter.check("login", "ip", limit=1, window=10)
    with pytest.raises(AppError) as exc:
        limiter.check("login", "ip", limit=1, window=10)
    assert exc.value.status == 429
    limiter.check("register", "ip", limit=1, window=10)
    now[0] = 11
    limiter.check("login", "ip", limit=1, window=10)


def test_embedded_preview_is_explicit_and_disallowed_in_production():
    preview = Settings(embedded_preview=True, _env_file=None)
    assert preview.cookie_secure is True and preview.cookie_samesite == "none"
    normal = Settings(embedded_preview=False, session_cookie_secure=False, _env_file=None)
    assert normal.cookie_samesite == "lax" and normal.cookie_name == "uptimex_session"
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            embedded_preview=True,
            session_cookie_secure=True,
            database_url="postgresql+psycopg://user@db/uptimex",
            _env_file=None,
        )


def test_database_failure_makes_health_unavailable(app, client):
    from sqlalchemy.exc import OperationalError

    from app.core.database import get_db

    class Unavailable:
        def execute(self, _):
            raise OperationalError("database unavailable", {}, Exception("offline"))

    app.dependency_overrides[get_db] = lambda: Unavailable()
    result = client.get("/api/v1/health")
    assert result.status_code == 503
    assert result.json()["database"] == "error"


def test_unexpected_exceptions_do_not_expose_internal_details(app, client):
    @app.get("/api/v1/test-failure")
    def broken():
        raise RuntimeError("internal-sensitive-details")

    result = client.get("/api/v1/test-failure")
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "internal-sensitive-details" not in result.text
    assert result.headers["X-Request-ID"]


def test_interactive_reference_documents_the_write_header(client):
    schema = client.get("/api/openapi.json").json()
    parameters = schema["paths"]["/api/v1/monitors"]["post"]["parameters"]
    assert any(
        p["name"] == "X-UptimeX-Client" and p["schema"]["default"] == "web" for p in parameters
    )


def test_combined_preview_serves_dashboard_and_keeps_api_errors_json(tmp_path, monkeypatch):
    from app.main import create_app

    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body>UptimeX dashboard</body></html>"
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('dashboard')")
    settings = Settings(frontend_dist=tmp_path, _env_file=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with TestClient(create_app()) as browser:
        response = browser.get("/")
        assert response.status_code == 200 and "text/html" in response.headers["content-type"]
        assert "UptimeX dashboard" in response.text
        assert browser.get("/assets/app.js").status_code == 200
        missing = browser.get("/api/v1/not-a-route")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "HTTP_ERROR"


def test_combined_preview_fails_fast_for_missing_build(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(
        "app.main.get_settings", lambda: Settings(frontend_dist=tmp_path, _env_file=None)
    )
    with pytest.raises(RuntimeError, match="built dashboard"):
        create_app()

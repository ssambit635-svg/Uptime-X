import os
import uuid
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.database import Base, get_db
from app.main import create_app
from app.services import url_policy

PASSWORD = "a-long-unique-password"


@pytest.fixture
def db_engine() -> Generator[Engine, None, None]:
    url = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    parsed = make_url(url)
    schema = None
    base_engine = None
    if parsed.get_backend_name() != "sqlite":
        # Isolate each case from public tables and migration state, even in a test DB.
        assert parsed.database and parsed.database.endswith("_test"), "Use a disposable *_test DB"
        schema = f"test_{uuid.uuid4().hex}"
        base_engine = create_engine(url, pool_pre_ping=True)
        with base_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = base_engine.execution_options(schema_translate_map={None: schema})
    else:
        assert parsed.database == ":memory:", "SQLite tests must use an isolated in-memory database"
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        if schema and base_engine:
            with base_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        else:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db(db_engine: Engine) -> Generator[Session, None, None]:
    with Session(db_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def app(db_engine: Engine) -> FastAPI:
    app = create_app()

    def test_db():
        with Session(db_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    return app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app, headers={"X-UptimeX-Client": "web"}) as client:
        yield client


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    response = client.post(
        "/api/v1/auth/register", json={"email": "owner@example.com", "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return client


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Integration tests never depend on internet DNS or contact a target website.
    monkeypatch.setattr(url_policy, "resolve_public_host", lambda _: ["93.184.216.34"])

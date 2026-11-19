import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url

from app.workers.bootstrap import bootstrap


@pytest.fixture
def bootstrap_env(monkeypatch):
    for key, value in {
        "AWS_REGION": "ap-south-1",
        "MASTER_SECRET_ARN": "master",
        "API_DATABASE_SECRET_ARN": "api-secret",
        "WORKER_DATABASE_SECRET_ARN": "worker-secret",
        "DB_HOST": "private-db.example.com",
        "DB_NAME": "uptimex_test",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    client = MagicMock()

    class Missing(Exception):
        pass

    client.exceptions.ResourceNotFoundException = Missing

    def value(SecretId):
        if SecretId == "master":
            return {"SecretString": json.dumps({"username": "owner", "password": "master-secret"})}
        if SecretId == "api-secret":
            return {"SecretString": json.dumps({"password": "existing-password"})}
        raise Missing()

    client.get_secret_value.side_effect = value
    connector = MagicMock()
    connector.return_value.execute.return_value.fetchone.return_value = None
    migrate = MagicMock()
    monkeypatch.setattr("alembic.command.upgrade", migrate)
    return client, connector, migrate


def test_private_bootstrap_migrates_and_issues_separate_non_owner_identities(bootstrap_env):
    client, connector, migrate = bootstrap_env
    bootstrap(client=client, connector=connector)
    migrate.assert_called_once()
    assert migrate.call_args.args[1] == "head"
    assert connector.call_args.kwargs["sslmode"] == "verify-full"
    assert connector.call_args.kwargs["sslrootcert"] == "/app/rds-ca.pem"
    payloads = {
        call.kwargs["SecretId"]: json.loads(call.kwargs["SecretString"])
        for call in client.put_secret_value.call_args_list
    }
    api = make_url(payloads["api-secret"]["database_url"])
    worker = make_url(payloads["worker-secret"]["database_url"])
    assert api.username == "uptimex_api" and api.password == "existing-password"
    assert worker.username == "uptimex_worker" and len(worker.password) >= 32
    assert worker.password != api.password
    assert api.query["sslmode"] == worker.query["sslmode"] == "verify-full"
    sql_statements = "\n".join(
        str(call.args[0]) for call in connector.return_value.execute.call_args_list
    )
    assert (
        "GRANT UPDATE (next_check_at, updated_at) ON monitors TO uptimex_worker" in sql_statements
    )
    assert "GRANT SELECT ON monitors TO uptimex_worker" in sql_statements
    assert "GRANT SELECT ON monitor_checks, service_heartbeats TO uptimex_api" in sql_statements
    assert "GRANT ALL" not in sql_statements and "SUPERUSER" not in sql_statements
    connector.return_value.close.assert_called_once()


def test_repeat_bootstrap_reuses_existing_roles_and_passwords(bootstrap_env):
    client, connector, _ = bootstrap_env
    connector.return_value.execute.return_value.fetchone.return_value = (1,)
    bootstrap(client=client, connector=connector)
    sql_statements = str(connector.return_value.execute.call_args_list)
    assert "CREATE ROLE" not in sql_statements
    api_payload = json.loads(client.put_secret_value.call_args_list[0].kwargs["SecretString"])
    assert api_payload["password"] == "existing-password"


def test_secret_write_failure_closes_privileged_connection(bootstrap_env):
    client, connector, _ = bootstrap_env
    client.put_secret_value.side_effect = RuntimeError("service unavailable")
    with pytest.raises(RuntimeError):
        bootstrap(client=client, connector=connector)
    connector.return_value.close.assert_called_once()

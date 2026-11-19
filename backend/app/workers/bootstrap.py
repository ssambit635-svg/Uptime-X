"""Privileged private-network AWS bootstrap/migration task; never an HTTP endpoint.

Uses RDS-managed master credentials only inside a one-off operator-invoked task.
Creates separate API/worker database identities; secrets never enter Terraform state,
command arguments, logs or git. Reruns reuse existing identities/passwords safely.
"""

import json
import os
import secrets

import boto3
import psycopg
from botocore.config import Config as SDKConfig
from psycopg import sql
from sqlalchemy.engine import URL


def bootstrap(client=None, connector=None) -> None:
    region = os.environ["AWS_REGION"]
    client = client or boto3.client(
        "secretsmanager",
        region_name=region,
        config=SDKConfig(
            connect_timeout=3,
            read_timeout=5,
            ignore_configured_endpoint_urls=True,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )
    master = json.loads(
        client.get_secret_value(SecretId=os.environ["MASTER_SECRET_ARN"])["SecretString"]
    )
    host = os.environ["DB_HOST"]
    database = os.environ.get("DB_NAME", "uptimex")
    ssl = {"sslmode": "verify-full", "sslrootcert": "/app/rds-ca.pem"}
    admin_url = URL.create(
        "postgresql+psycopg",
        username=master["username"],
        password=master["password"],
        host=host,
        port=5432,
        database=database,
        query=ssl,
    )
    os.environ["DATABASE_URL"] = admin_url.render_as_string(hide_password=False)
    # Settings must be loaded only after the privileged DSN is in the process env.
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    connection = (connector or psycopg.connect)(
        host=host,
        port=5432,
        dbname=database,
        user=master["username"],
        password=master["password"],
        connect_timeout=5,
        **ssl,
    )
    try:
        for role, secret_name in [
            ("uptimex_api", "API_DATABASE_SECRET_ARN"),
            ("uptimex_worker", "WORKER_DATABASE_SECRET_ARN"),
        ]:
            arn = os.environ[secret_name]
            try:
                saved = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
                password = saved["password"]
            except client.exceptions.ResourceNotFoundException:
                password = secrets.token_urlsafe(32)
            with connection.transaction():
                if not connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
                ).fetchone():
                    connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                connection.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
                connection.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database), sql.Identifier(role)
                    )
                )
                connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
                )
                if role == "uptimex_api":
                    connection.execute(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON users, auth_sessions, "
                        "monitors, check_jobs TO uptimex_api"
                    )
                    connection.execute(
                        "GRANT SELECT ON monitor_checks, service_heartbeats TO uptimex_api"
                    )
                else:
                    connection.execute("GRANT SELECT ON monitors TO uptimex_worker")
                    connection.execute(
                        "GRANT UPDATE (next_check_at, updated_at) ON monitors TO uptimex_worker"
                    )
                    connection.execute(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON check_jobs, monitor_checks, "
                        "service_heartbeats TO uptimex_worker"
                    )
            url = URL.create(
                "postgresql+psycopg",
                username=role,
                password=password,
                host=host,
                port=5432,
                database=database,
                query=ssl,
            )
            client.put_secret_value(
                SecretId=arn,
                SecretString=json.dumps(
                    {
                        "database_url": url.render_as_string(hide_password=False),
                        "password": password,
                    }
                ),
            )
        connection.commit()
    finally:
        connection.close()
        os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    try:
        bootstrap()
    except Exception as exc:
        # No traceback: DB/SDK errors may contain credentials or secret contents.
        print(json.dumps({"bootstrap": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps({"bootstrap": "complete", "schema": "0002", "credentials_logged": False}))

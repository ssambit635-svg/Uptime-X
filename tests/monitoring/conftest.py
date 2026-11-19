import hashlib
import socket
import threading
from contextlib import suppress
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models.entities import CheckJob, Monitor, MonitorCheck, User, utcnow
from app.services.checker import MAX_BODY, HTTPChecker


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
def monitor(db):
    user = User(email="worker-test@example.com", password_hash="test-only-not-a-password")
    db.add(user)
    db.flush()
    target = "http://health.example.com/ok"
    item = Monitor(
        user_id=user.id,
        name="Worker test",
        target_url=target,
        target_fingerprint=hashlib.sha256(target.encode()).hexdigest(),
    )
    db.add(item)
    db.commit()
    return item


@pytest.fixture
def record(db):
    def add(monitor, outcome="UP", *, age=0, region="local", revision=None, total=50, status=200):
        now = utcnow() - timedelta(seconds=age)
        revision = revision or monitor.revision
        job = CheckJob(
            monitor_id=monitor.id,
            revision=revision,
            region=region,
            scheduled_at=now,
            state="COMPLETE",
        )
        db.add(job)
        db.flush()
        check = MonitorCheck(
            job_id=job.id,
            monitor_id=monitor.id,
            revision=revision,
            region=region,
            scheduled_at=now,
            started_at=now,
            checked_at=now,
            outcome=outcome,
            http_status=status,
            dns_ms=1,
            connect_ms=2,
            tls_ms=None,
            ttfb_ms=10,
            total_ms=total,
            response_bytes=7,
            redirect_count=0,
            error_category="HTTP_STATUS" if outcome == "FAILURE" else None,
        )
        db.add(check)
        db.commit()
        return check

    return add


@pytest.fixture
def public_http():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_GET(self):
            self.server.requests.append((self.path, dict(self.headers)))
            if self.path == "/slow":
                import time

                time.sleep(1.1)
            status = 503 if self.path == "/error" else 200
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "http://127.0.0.1/private" if self.path == "/redirect-private" else "/ok",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"healthy"
            self.send_response(status)
            self.send_header(
                "Content-Length", str(MAX_BODY + 1 if self.path == "/huge" else len(body))
            )
            self.end_headers()
            if self.path != "/huge":
                with suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class RoutedSocket:
        # Test-only controlled internet boundary. No production allow-private mode.
        def __init__(self, timeout):
            self.socket = socket.create_connection(server.server_address, timeout)

        def getpeername(self):
            return ("8.8.8.8", 80)

        def __getattr__(self, name):
            return getattr(self.socket, name)

    checker = HTTPChecker(
        resolver=lambda *_: ["8.8.8.8"], dialer=lambda ip, port, timeout: RoutedSocket(timeout)
    )
    yield checker, server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)

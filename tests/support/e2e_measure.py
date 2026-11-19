"""Controlled HTTP evidence for Playwright, never included in the runtime image.

Requires the exact disposable E2E database and a pre-queued job ID. No production
allow-private flag or test endpoint exists: only this test constructs a routed
socket boundary. Measurements come from an actual local HTTP exchange, not a
pre-filled row or fabricated timing. This does not verify public-internet/AWS egress.
"""

import os
import socket
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if os.environ.get("APP_ENV") != "test" or os.environ.get("DATABASE_URL") != (
    "sqlite:///./.local/e2e.db"
):
    raise SystemExit("This helper only accepts the isolated Playwright test database")

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.checker import HTTPChecker  # noqa: E402
from app.services.jobs import execute_job  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        body = b"controlled-e2e-response"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()


class RoutedSocket:
    def __init__(self, ip, port, timeout):
        assert ip == "8.8.8.8" and port == 80
        self.socket = socket.create_connection(server.server_address, timeout=timeout)

    def getpeername(self):
        return ("8.8.8.8", 80)

    def __getattr__(self, name):
        return getattr(self.socket, name)


try:
    checker = HTTPChecker(dialer=RoutedSocket)
    action = execute_job(SessionLocal, uuid.UUID(sys.argv[1]), "local", get_settings(), checker)
    if action != "ack":
        raise SystemExit("Controlled test check did not persist")
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)

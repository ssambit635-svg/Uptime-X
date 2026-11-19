import errno
import socket
import ssl
from unittest.mock import Mock

import pytest

from app.services.checker import MAX_BODY, Deadline, HTTPChecker, dial_public
from app.services.url_policy import UnsafeTarget


def test_real_bounded_get_records_measurements_without_content(public_http):
    checker, server = public_http
    result = checker.check("http://health.example.com/ok")
    assert result.outcome == "UP" and result.http_status == 200
    assert result.response_bytes == 7 and result.total_ms > 0
    assert all(getattr(result, key) is not None for key in ["dns_ms", "connect_ms", "ttfb_ms"])
    assert result.tls_ms is None and "body" not in result.values()
    headers = server.requests[0][1]
    assert headers["Host"] == "health.example.com" and headers["Accept-Encoding"] == "identity"
    assert "Cookie" not in headers and "Authorization" not in headers
    assert (
        checker.tls_context.check_hostname and checker.tls_context.verify_mode == ssl.CERT_REQUIRED
    )


@pytest.mark.parametrize(
    "path,outcome,category",
    [
        ("/error", "FAILURE", "HTTP_STATUS"),
        ("/redirect-public", "UP", None),
        ("/redirect-private", "UNKNOWN", "POLICY_BLOCKED"),
        ("/huge", "UNKNOWN", "RESPONSE_LIMIT"),
        ("/slow", "FAILURE", "TIMEOUT"),
    ],
)
def test_endpoint_outcomes_are_categorized_and_bounded(public_http, path, outcome, category):
    checker, server = public_http
    result = checker.check("http://health.example.com" + path, timeout=1)
    assert (result.outcome, result.error_category) == (outcome, category)
    assert result.total_ms < 1800
    assert len(server.requests) <= 2


def test_latency_policy_and_expected_status_are_applied(public_http):
    checker, _ = public_http
    assert checker.check("http://health.example.com/ok", slow_ms=0).outcome == "DEGRADED"
    assert (
        checker.check("http://health.example.com/error", expected_min=500, expected_max=599).outcome
        == "UP"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]",
        "file:///etc/passwd",
        "http://user:pass@example.com",
        "http://example.com:5432",
        "http://example.com/\r\nInjected:yes",
    ],
)
def test_unsafe_urls_never_dial(url):
    dialer = Mock()
    assert HTTPChecker(dialer=dialer).check(url).outcome == "UNKNOWN"
    dialer.assert_not_called()


@pytest.mark.parametrize(
    "answers", [["8.8.8.8", "10.0.0.1"], ["169.254.170.2"], [], ["::ffff:8.8.8.8"]]
)
def test_all_dns_answers_must_be_public(answers):
    dialer = Mock()
    result = HTTPChecker(resolver=lambda *_: answers, dialer=dialer).check(
        "http://public.example.com"
    )
    assert result.error_category == "POLICY_BLOCKED"
    dialer.assert_not_called()


def test_hostname_is_never_resolved_again_by_the_socket(public_http):
    checker, _ = public_http
    actual = checker.dialer
    called = []

    def dial(ip, port, timeout):
        called.append((ip, port))
        return actual(ip, port, timeout)

    checker.dialer = dial
    checker.check("http://health.example.com/ok")
    assert called == [("8.8.8.8", 80)]


def test_dns_rebinding_on_redirect_is_revalidated(public_http):
    checker, server = public_http
    replies = iter([["8.8.8.8"], ["127.0.0.1"]])
    checker.resolver = lambda *_: next(replies)
    result = checker.check("http://health.example.com/redirect-public")
    assert result.error_category == "POLICY_BLOCKED"
    assert len(server.requests) == 1


def test_peer_must_match_the_validated_numeric_ip():
    connection = Mock()
    connection.getpeername.return_value = ("1.1.1.1", 80)
    result = HTTPChecker(dialer=lambda *_: connection).check("http://8.8.8.8")
    assert result.error_category == "PEER_MISMATCH"
    connection.sendall.assert_not_called()
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "error,category",
    [
        (ssl.SSLError("certificate"), "TLS"),
        (OSError("refused"), "CONNECT"),
        (TimeoutError(), "TIMEOUT"),
    ],
)
def test_network_errors_do_not_expose_details(error, category):
    result = HTTPChecker(dialer=Mock(side_effect=error)).check("https://8.8.8.8")
    assert result.outcome == "FAILURE" and result.error_category == category
    assert "certificate" not in str(result.values())


def test_tls_uses_original_hostname_not_pinned_ip():
    connection = Mock()
    connection.getpeername.return_value = ("8.8.8.8", 443)
    context = Mock()
    context.wrap_socket.side_effect = ssl.SSLError("bad cert")
    result = HTTPChecker(
        resolver=lambda *_: ["8.8.8.8"], dialer=lambda *_: connection, tls_context=context
    ).check("https://health.example.com")
    assert result.error_category == "TLS"
    context.wrap_socket.assert_called_once_with(connection, server_hostname="health.example.com")


def test_dns_failure_is_not_an_internal_platform_error():
    checker = HTTPChecker(resolver=Mock(side_effect=UnsafeTarget("DNS failure")))
    result = checker.check("https://health.example.com")
    assert result.error_category == "DNS" and result.outcome == "FAILURE"


def test_socket_dialer_uses_numeric_address_and_closes_on_failure(monkeypatch):
    connection = Mock()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(socket, "socket", factory)
    assert dial_public("8.8.8.8", 443, 2) is connection
    connection.connect.assert_called_once_with(("8.8.8.8", 443))
    factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    connection.connect.side_effect = OSError
    with pytest.raises(OSError):
        dial_public("8.8.8.8", 80, 1)
    connection.close.assert_called_once()
    with pytest.raises(UnsafeTarget):
        dial_public("127.0.0.1", 80, 1)


def test_absolute_deadline_expires(monkeypatch):
    deadline = Deadline(1)
    monkeypatch.setattr("app.services.checker.time.monotonic", lambda: deadline.end + 1)
    with pytest.raises(TimeoutError):
        deadline.remaining()


class Wire:
    def __init__(self, body):
        self.body = body

    def getpeername(self):
        return ("8.8.8.8", 80)

    def settimeout(self, _):
        pass

    def sendall(self, _):
        pass

    def close(self):
        pass

    def recv(self, size):
        part, self.body = self.body[:size], self.body[size:]
        return part


@pytest.mark.parametrize(
    "wire,category",
    [
        (b"not HTTP at all\r\n\r\n", "HTTP_PROTOCOL"),
        (b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n", "REDIRECT_POLICY"),
        (
            b"HTTP/1.1 101 Switching Protocols\r\nConnection: upgrade\r\nUpgrade: ws\r\n\r\n",
            "HTTP_PROTOCOL",
        ),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            + f"{MAX_BODY + 1:x}\r\n".encode()
            + b"x" * (MAX_BODY + 1)
            + b"\r\n0\r\n\r\n",
            "RESPONSE_LIMIT",
        ),
    ],
)
def test_raw_protocol_limits(wire, category):
    result = HTTPChecker(dialer=lambda *_: Wire(wire)).check("http://8.8.8.8")
    assert result.error_category == category
    assert result.response_bytes <= MAX_BODY + 8192


def test_redirect_limit_stops_unbounded_loops(public_http):
    checker, server = public_http
    # Each response redirects to itself; four requests maximum.
    checker._exchange = lambda *_: "/loop"
    result = checker.check("http://health.example.com/loop")
    assert result.error_category == "REDIRECT_LIMIT" and result.redirect_count == 3
    assert server.requests == []


@pytest.mark.parametrize("code", [errno.ENETUNREACH, errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL])
def test_worker_network_capability_failures_are_unknown_not_target_downtime(code):
    dialer = Mock(side_effect=OSError(code, "local transport unavailable"))
    result = HTTPChecker(dialer=dialer).check("http://[2606:4700:4700::1111]")
    assert result.outcome == "UNKNOWN" and result.error_category == "WORKER_NETWORK"

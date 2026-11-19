"""One bounded, DNS-pinned HTTP GET. No proxy, cookies, credentials, or body persistence.

Every redirect gets a fresh policy check and DNS resolution. The only network dial
uses a validated numeric IP; TLS still verifies the original host/SNI. Production
has no flag permitting private destinations or disabling certificate verification.
"""

import errno
import ipaddress
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit

import h11

from app.services.url_policy import (
    UnsafeTarget,
    is_public_ip,
    resolve_public_host,
    validate_target_url,
)

MAX_BODY = 262_144
MAX_HEADERS = 32_768
MAX_REDIRECTS = 3


class CheckFailure(Exception):
    def __init__(self, category: str, *, inconclusive: bool = False):
        self.category = category
        self.inconclusive = inconclusive


@dataclass
class Observation:
    outcome: str = "UNKNOWN"
    http_status: int | None = None
    dns_ms: float | None = None
    connect_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    total_ms: float = 0
    response_bytes: int = 0
    redirect_count: int = 0
    error_category: str | None = None

    def values(self) -> dict:
        return asdict(self)


class Deadline:
    def __init__(self, seconds: float):
        self.started = time.monotonic()
        self.end = self.started + seconds

    def remaining(self) -> float:
        value = self.end - time.monotonic()
        if value <= 0:
            raise TimeoutError
        return value


def dial_public(ip: str, port: int, timeout: float) -> socket.socket:
    if not is_public_ip(ip) or port not in {80, 443}:
        raise UnsafeTarget("Connection destination is prohibited.")
    # Do not use create_connection(hostname), requests, environment proxies or a
    # transport that could perform a second, unvalidated DNS lookup.
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    connection = socket.socket(family, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect((ip, port))
        return connection
    except BaseException:
        connection.close()
        raise


class HTTPChecker:
    def __init__(
        self,
        *,
        resolver: Callable[[str, float], list[str]] | None = None,
        dialer: Callable = dial_public,
        tls_context: ssl.SSLContext | None = None,
    ):
        self.resolver = resolver or (lambda host, budget: resolve_public_host(host, min(2, budget)))
        self.dialer = dialer
        self.tls_context = tls_context or ssl.create_default_context()

    def check(
        self,
        url: str,
        timeout: int = 10,
        expected_min: int = 200,
        expected_max: int = 299,
        slow_ms: int = 2000,
    ) -> Observation:
        deadline = Deadline(min(10, max(1, timeout)))
        result = Observation()
        phase = "DNS"
        try:
            for hop in range(MAX_REDIRECTS + 1):
                result.redirect_count = hop
                phase = "POLICY"
                target = validate_target_url(url, resolve_dns=False)
                parsed = urlsplit(target)
                host = parsed.hostname
                assert host is not None
                phase = "DNS"
                started = time.monotonic()
                try:
                    literal = ipaddress.ip_address(host)
                except ValueError:
                    literal = None
                addresses = [host] if literal else self.resolver(host, deadline.remaining())
                deadline.remaining()
                result.dns_ms = (result.dns_ms or 0) + (time.monotonic() - started) * 1000
                if not addresses or not all(is_public_ip(ip) for ip in addresses):
                    raise CheckFailure("POLICY_BLOCKED", inconclusive=True)
                # A single pinned attempt per check bounds resource use. Subsequent
                # scheduled checks may choose another healthy DNS answer.
                ip = addresses[0]
                phase = "CONNECT"
                started = time.monotonic()
                connection = self.dialer(
                    ip,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    deadline.remaining(),
                )
                try:
                    peer = connection.getpeername()[0]
                    if not is_public_ip(peer) or ipaddress.ip_address(peer) != ipaddress.ip_address(
                        ip
                    ):
                        raise CheckFailure("PEER_MISMATCH", inconclusive=True)
                    result.connect_ms = (result.connect_ms or 0) + (
                        time.monotonic() - started
                    ) * 1000
                    if parsed.scheme == "https":
                        phase = "TLS"
                        started = time.monotonic()
                        connection.settimeout(deadline.remaining())
                        connection = self.tls_context.wrap_socket(connection, server_hostname=host)
                        result.tls_ms = (result.tls_ms or 0) + (time.monotonic() - started) * 1000
                    phase = "HTTP"
                    location = self._exchange(connection, parsed, result, deadline)
                finally:
                    connection.close()
                if location is None:
                    result.outcome = (
                        "UP" if expected_min <= result.http_status <= expected_max else "FAILURE"
                    )
                    if result.outcome == "FAILURE":
                        result.error_category = "HTTP_STATUS"
                    break
                if hop == MAX_REDIRECTS:
                    raise CheckFailure("REDIRECT_LIMIT", inconclusive=True)
                following = urljoin(target, location)
                if parsed.scheme == "https" and urlsplit(following).scheme == "http":
                    raise CheckFailure("TLS_DOWNGRADE", inconclusive=True)
                url = following
        except UnsafeTarget:
            result.outcome = "FAILURE" if phase == "DNS" else "UNKNOWN"
            result.error_category = "DNS" if phase == "DNS" else "POLICY_BLOCKED"
        except CheckFailure as exc:
            result.outcome = "UNKNOWN" if exc.inconclusive else "FAILURE"
            result.error_category = exc.category
        except TimeoutError:
            result.outcome, result.error_category = "FAILURE", "TIMEOUT"
        except ssl.SSLError:
            result.outcome, result.error_category = "FAILURE", "TLS"
        except (h11.ProtocolError, UnicodeError, ValueError):
            result.outcome, result.error_category = "FAILURE", "HTTP_PROTOCOL"
        except OSError as exc:
            if exc.errno in {errno.ENETUNREACH, errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
                # E.g. an IPv6-only endpoint from an IPv4-only worker subnet.
                # Missing worker network capability is not a failed target.
                result.outcome, result.error_category = "UNKNOWN", "WORKER_NETWORK"
            else:
                result.outcome, result.error_category = "FAILURE", phase
        result.total_ms = round((time.monotonic() - deadline.started) * 1000, 3)
        if result.outcome == "UP" and result.total_ms > slow_ms:
            result.outcome = "DEGRADED"
        for name in ("dns_ms", "connect_ms", "tls_ms", "ttfb_ms"):
            if (value := getattr(result, name)) is not None:
                setattr(result, name, round(value, 3))
        return result

    def _exchange(self, connection, parsed, result: Observation, deadline: Deadline) -> str | None:
        protocol = h11.Connection(h11.CLIENT, max_incomplete_event_size=MAX_HEADERS)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = h11.Request(
            method=b"GET",
            target=path.encode("ascii"),
            headers=[
                (b"Host", parsed.netloc.encode("ascii")),
                (b"User-Agent", b"UptimeX/0.2 (authorized website health monitoring)"),
                (b"Accept", b"*/*"),
                (b"Accept-Encoding", b"identity"),
                (b"Connection", b"close"),
            ],
        )
        connection.settimeout(deadline.remaining())
        connection.sendall(protocol.send(request) + protocol.send(h11.EndOfMessage()))
        header_bytes = 0
        headers_received = False
        first_byte = True
        while True:
            deadline.remaining()
            event = protocol.next_event()
            if event is h11.NEED_DATA:
                connection.settimeout(deadline.remaining())
                chunk = connection.recv(8192)
                if first_byte and chunk:
                    result.ttfb_ms = (time.monotonic() - deadline.started) * 1000
                    first_byte = False
                if not headers_received:
                    header_bytes += len(chunk)
                    # At most one receive chunk of body is included in this bound.
                    if header_bytes > MAX_HEADERS + 8192:
                        raise CheckFailure("HEADER_LIMIT", inconclusive=True)
                protocol.receive_data(chunk)
            elif isinstance(event, h11.InformationalResponse):
                if event.status_code == 101:
                    raise CheckFailure("HTTP_UPGRADE", inconclusive=True)
            elif isinstance(event, h11.Response):
                headers_received = True
                result.http_status = event.status_code
                headers = dict(event.headers)
                if event.status_code in {301, 302, 303, 307, 308}:
                    location = headers.get(b"location")
                    if not location or len(location) > 2048:
                        raise CheckFailure("REDIRECT_POLICY", inconclusive=True)
                    return location.decode("ascii")
                length = headers.get(b"content-length")
                if length and int(length) > MAX_BODY:
                    raise CheckFailure("RESPONSE_LIMIT", inconclusive=True)
            elif isinstance(event, h11.Data):
                result.response_bytes += len(event.data)
                if result.response_bytes > MAX_BODY:
                    raise CheckFailure("RESPONSE_LIMIT", inconclusive=True)
            elif isinstance(event, h11.EndOfMessage):
                return None
            elif isinstance(event, h11.ConnectionClosed):
                raise CheckFailure("HTTP_PROTOCOL")

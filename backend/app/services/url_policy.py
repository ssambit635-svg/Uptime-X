import ipaddress
import re
import time
from urllib.parse import quote, urlsplit, urlunsplit

import dns.exception
import dns.resolver

from app.core.errors import AppError


class UnsafeTarget(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(422, "UNSAFE_TARGET", message)


# Reject translation/tunnelling ranges as well as non-global destinations.
BLOCKED_V6 = tuple(
    ipaddress.ip_network(network)
    for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)
BLOCKED_V4 = ipaddress.ip_network("192.0.0.0/24")


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address not in BLOCKED_V4
    return not address.ipv4_mapped and not any(address in network for network in BLOCKED_V6)


def resolve_public_host(host: str, lifetime: float = 2.0) -> list[str]:
    """Bounded DNS-only validation; this does not make an HTTP request."""
    addresses: list[str] = []
    resolver = dns.resolver.Resolver()
    deadline = time.monotonic() + lifetime
    for record_type in ("A", "AAAA"):
        try:
            answer = resolver.resolve(
                host, record_type, search=False, lifetime=max(0.001, deadline - time.monotonic())
            )
            addresses.extend(record.address for record in answer)
        except dns.resolver.NoAnswer:
            continue
        except (dns.exception.DNSException, OSError) as exc:
            raise UnsafeTarget(
                "This hostname could not be safely resolved. Please try again."
            ) from exc
    if not addresses:
        raise UnsafeTarget("This hostname has no public IP addresses.")
    return addresses


def validate_target_url(raw_url: str, *, resolve_dns: bool = True) -> str:
    """Canonicalize public HTTP(S) syntax; save-time DNS validation is the default.

    The checker disables this preliminary DNS lookup, then independently validates
    every resolution and pins its actual socket to a validated numeric address.
    Literal addresses are always validated, even when resolve_dns is false.
    """
    if any(ord(char) < 32 or ord(char) == 127 for char in raw_url) or "\\" in raw_url:
        raise UnsafeTarget("Use a URL without control characters or backslashes.")
    raw_url = raw_url.strip()
    if len(raw_url) > 2048:
        raise UnsafeTarget("The URL must be 2,048 characters or fewer.")
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTarget("Enter a valid public HTTP or HTTPS URL.") from exc
    if parsed.scheme not in {"http", "https"} or not host:
        raise UnsafeTarget("Use a full public URL starting with https:// or http://.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTarget("URLs containing usernames or passwords are not allowed.")
    if parsed.fragment:
        raise UnsafeTarget("Remove the fragment (the part after #) from this URL.")
    if port is not None and port not in {80, 443}:
        raise UnsafeTarget("Only public HTTP/HTTPS ports 80 and 443 are allowed.")
    host = host.rstrip(".").lower()
    if "%" in host:
        raise UnsafeTarget("Scoped or encoded host addresses are not allowed.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is None:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeTarget("Enter a valid hostname.") from exc
        labels = host.split(".")
        if (
            len(host) > 253
            or len(labels) < 2
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
            or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
            or re.fullmatch(r"[0-9.]+", host)
        ):
            raise UnsafeTarget("Use a publicly resolvable hostname, not a local network address.")
        addresses = resolve_public_host(host) if resolve_dns else None
    else:
        host = literal.compressed
        addresses = [host]
    if addresses is not None and (not addresses or not all(is_public_ip(a) for a in addresses)):
        raise UnsafeTarget("Private, local, reserved and metadata addresses are not allowed.")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
        netloc += f":{port}"
    safe = "/:@!$&'()*+,;=-._~%"
    result = urlunsplit(
        (
            parsed.scheme,
            netloc,
            quote(parsed.path or "/", safe=safe),
            quote(parsed.query, safe=safe + "?"),
            "",
        )
    )
    if len(result) > 2048:
        raise UnsafeTarget("The normalized URL must be 2,048 characters or fewer.")
    return result

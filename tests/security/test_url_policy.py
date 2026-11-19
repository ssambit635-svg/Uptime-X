from types import SimpleNamespace

import dns.exception
import dns.resolver
import pytest

from app.services import url_policy
from app.services.url_policy import UnsafeTarget, is_public_ip, validate_target_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "gopher://example.com",
        "javascript:alert(1)",
        "//example.com",
        "example.com",
        "https://",
        "https://user:password@example.com",
        "https://user@example.com",
        "https://example.com:8080",
        "https://example.com:99999",
        "https://example.com:abc",
        "https://example.com/#secret",
        "https://example.com\\@evil.com",
        "https://exam\nple.com",
        "https://example.com/\x00",
        "http://localhost",
        "http://a.local",
        "http://api.internal",
        "http://service.localhost",
        "http://metadata.google.internal",
        "http://127.0.0.1",
        "http://127.1",
        "http://2130706433",
        "http://0x7f000001",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.0.1",
        "http://0.0.0.0",
        "http://169.254.169.254",
        "http://100.100.100.200",
        "http://224.0.0.1",
        "http://192.0.0.8",
        "http://192.0.2.1",
        "http://198.51.100.1",
        "http://203.0.113.1",
        "http://[::1]",
        "http://[::]",
        "http://[fc00::1]",
        "http://[fe80::1]",
        "http://[::ffff:127.0.0.1]",
        "http://[::ffff:8.8.8.8]",
        "http://[fe80::1%25eth0]",
        "http://[64:ff9b::7f00:1]",
        "http://[2002:7f00:1::]",
        "https://-bad.example.com",
        "https://bad_.example.com",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_rejects_unsafe_or_ambiguous_targets(url, monkeypatch):
    # Alternate numeric representations resolving to loopback must still fail closed.
    monkeypatch.setattr(url_policy, "resolve_public_host", lambda _: ["127.0.0.1"])
    with pytest.raises(UnsafeTarget):
        validate_target_url(url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://EXAMPLE.com:443", "https://example.com/"),
        ("http://example.com:80/health?q=1", "http://example.com/health?q=1"),
        ("https://example.com./a", "https://example.com/a"),
        ("https://example.com/café", "https://example.com/caf%C3%A9"),
        ("https://例え.jp/", "https://xn--r8jz45g.jp/"),
        ("https://8.8.8.8/", "https://8.8.8.8/"),
        ("https://[2606:4700:4700::1111]", "https://[2606:4700:4700::1111]/"),
    ],
)
def test_accepts_and_normalizes_public_targets(raw, expected, public_dns):
    assert validate_target_url(raw) == expected


def test_rejects_host_with_any_non_public_dns_answer(monkeypatch):
    monkeypatch.setattr(url_policy, "resolve_public_host", lambda _: ["8.8.8.8", "10.0.0.1"])
    with pytest.raises(UnsafeTarget):
        validate_target_url("https://example.com")


def test_dns_validation_has_bounded_resolution(monkeypatch):
    calls = []

    def resolve(_, host, record_type, **kwargs):
        calls.append((host, record_type, kwargs))
        return [SimpleNamespace(address="8.8.8.8" if record_type == "A" else "2606:4700::1111")]

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", resolve)
    assert url_policy.resolve_public_host("example.com") == ["8.8.8.8", "2606:4700::1111"]
    assert [call[1] for call in calls] == ["A", "AAAA"]
    assert all(call[2] == {"search": False, "lifetime": 2.0} for call in calls)


@pytest.mark.parametrize("error", [dns.resolver.NXDOMAIN, dns.exception.Timeout, OSError])
def test_dns_failures_are_rejected(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", fail)
    with pytest.raises(UnsafeTarget):
        url_policy.resolve_public_host("example.com")


def test_missing_dns_records_are_rejected(monkeypatch):
    def no_answer(*args, **kwargs):
        raise dns.resolver.NoAnswer()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", no_answer)
    with pytest.raises(UnsafeTarget):
        url_policy.resolve_public_host("example.com")


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_ip_classification(address):
    assert is_public_ip(address)

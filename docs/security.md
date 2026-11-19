# Security boundaries for the foundation slice

## Implemented

**Identity.** Passwords use pwdlib's recommended Argon2id implementation. Opaque session tokens are
cryptographically random; only SHA-256 digests are stored. Sessions expire, rotate on login, and are
revoked on logout. Cookies are HttpOnly and host-only. Production requires Secure cookies and
PostgreSQL; development may use HTTP/SQLite. The optional HTTPS iframe-preview mode uses
Secure + SameSite=None + Partitioned cookies and is prohibited in production. It does not relax CSRF.

**Development-preview exception.** When `EMBEDDED_PREVIEW=true`, an explicit
`X-UptimeX-Session-Mode: preview` login/register request also returns a short-lived opaque session.
The browser can send it in `X-UptimeX-Preview-Session` if an embedding browser/proxy blocks cookies.
It uses the same digest-only session table, ownership checks, expiry, login rotation and logout
revocation; merely supplying the mode/client headers never authenticates a request. Its lifetime is
60 minutes by default, configurable only between 5 and 120 minutes. The header transport is ignored
outside preview mode, and settings reject enabling preview mode in production.

This credential is held in memory and tab-scoped sessionStorage, **not localStorage**, and is cleared
on logout, expiry or a protected 401. It is deliberately JavaScript-readable and therefore **does not
have an HttpOnly cookie's protection against token theft by same-origin XSS**. Keep preview mode
limited to trusted, non-production HTTPS previews; never enable it for public launch. No password is
stored in browser storage. If storage is denied entirely, only a page-lifetime session is possible.
See [ADR 002](decisions/0002-preview-sessions.md) for the motivation and security tradeoff.

**CSRF.** Mutating `/api/` requests require `X-UptimeX-Client: web`; cross-origin browser scripts must
preflight to set it, and this API grants no CORS permission. When present, Origin must match the
incoming Host; malformed, null and cross-site origins are rejected. `Sec-Fetch-Site: cross-site` is
also rejected. GET requests do not mutate state. Proxies must preserve the public Host. Do not add
credentialed CORS for arbitrary origins or trust forwarded Host/IP headers without a reviewed design.

**Authorization.** Every monitor operation includes the authenticated owner in its query. Missing
and other users' records both return 404. There is no admin/lab execution API. Writes never accept a
user ID, observed status, measured metrics or arbitrary SQL fields from the client.

**URL setup.** Only HTTP/HTTPS and ports 80/443; no embedded credentials, fragments, malformed hosts,
control characters, backslashes, local/single-label names or scoped IPv6. Both A and AAAA records
are resolved with bounded lifetimes; *any* non-public result rejects the hostname. Private,
loopback, reserved, shared-address/metadata, multicast, translation and tunnelling destinations are
rejected. Errors fail closed. Canonical targets are deduplicated per owner; account limits are 10,
with a PostgreSQL owner-row lock to serialize concurrent quota decisions.

**Data.** No target response bodies, fake check data, passwords in browser storage, analytics tracking
or external favicon requests. Normal local/production session tokens stay in HttpOnly cookies;
short-lived development-preview credentials are the explicitly documented exception above.
Validation errors do not echo inputs. Request logs exclude query strings, request bodies and session
headers. Auth responses use `Cache-Control: no-store`; credentials never go in URLs.
Secrets/local databases/test artifacts are ignored. API errors include stable machine codes and
request IDs; unexpected failures do not return tracebacks.

## Explicitly not solved by URL setup

DNS validation when saving a URL is **not** SSRF-safe HTTP execution. There is no HTTP checker in
this release. Before one is introduced, the worker must independently revalidate every resolution
and redirect, validate and pin the actual connection destination, preserve correct Host/SNI and TLS
verification, cap ports/hops/body/time/concurrency, and be isolated from the control plane/metadata
network by egress controls. Tests must include rebinding and a public URL redirecting to a private
address. Never implement the worker as `requests.get(stored_url)` or an unrestricted HTTP client.

## Before any public launch

1. Email ownership verification, account recovery/deletion policy, session administration and abuse controls.
2. Shared rate limits/concurrency controls and a trusted ingress/proxy design. Current auth limits are
   deliberately in-memory, single-process only. Keep `--no-proxy-headers` until a trusted proxy is configured.
3. HTTPS termination, secure-cookie review, CSP review and managed production secrets.
4. Outbound worker isolation plus execution-time SSRF and bounded-request tests.
5. Account/monitor ownership policy enforcement appropriate to an Internet-facing service.
6. Database backups and verified restoration, retention/deletion policy, operator alerts and cost budgets.
7. Load, dependency, security and deployment review. Compose is development-only, with local credentials.

The API is not a network scanner, traffic generator, arbitrary-header requester or cloud executor.
REAL monitor configuration is the only current data domain. SIMULATED and LAB tables/APIs are not
created prematurely; they must remain separate when implemented.

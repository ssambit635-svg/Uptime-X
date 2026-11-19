# Security boundaries — monitoring implementation / AWS acceptance pending

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

## Execution-time boundary

Save-time DNS validation is still **not** a permanent permission to fetch an address. The checker
revalidates every request/redirect, validates every A/AAAA answer, dials a pinned numeric public IP,
verifies the peer, and keeps the original Host/TLS SNI and CA/hostname validation. Raw sockets never
read environment proxy settings or perform a second hostname lookup. There is no production
allow-private or disable-TLS flag, custom header/body input, cookie forwarding or credentialed URL.

A check has an absolute maximum 10-second budget, at most 3 redirects, bounded headers and a 256 KiB
body budget (one bounded receive can detect an over-limit response). It does not decompress or store
response bodies. HTTPS downgrade and redirect-to-private/rebinding are refused. UNKNOWN policy/size
or worker-network capability errors are not target-downtime evidence. Tests include controlled real
HTTP, forbidden redirects, rebinding, mixed public/private DNS, peer mismatch, malformed/chunked
responses, certificate errors and timeout. Test-only routed sockets are not shipped in the image.

Cloud workers use private IPv4 subnets, no inbound rules, restricted HTTP(S)/DB egress ports and NACL
rules denying private HTTP(S) ranges. Link-local AWS credential/DNS traffic has platform exceptions:
these controls complement, never replace, socket policy. The staging network/permissions still need
live verification; source code/static tests do not demonstrate effective AWS isolation.

## Distributed jobs and privileges

Only an authenticated owner's monitor can request work. SQS envelopes are limited to 1 KiB of UTF-8,
strict schema version, job UUID and configured region: no target URLs or HTTP instructions. Workers
load current, authorized configuration from the database. Region mismatch/poison/dead deliveries
are not silently acknowledged. SDK calls have bounded timeouts/retries and ignore configured endpoint
URL overrides. Task roles supply AWS credentials; no key/secret fields are accepted in API payloads.

Monitor row locks serialize scheduling/configuration changes; token-fenced leases and unique job
results reject duplicates, expired leases and old-policy completions. Paused/deleted monitors must
not run. Internal worker errors retry/dead-letter without writing a fabricated target failure.
Only the operator CLI can deliberately replay DEAD work with explicit confirmation. Replay means a
fresh current-policy check, not changing history or bulk redriving every DLQ message.

The Terraform staging design separates API, scheduler and regional consumer IAM roles. Normal tasks
use distinct non-owner database roles; only a one-off private bootstrap task reads the RDS-managed
master secret and provisions restricted credentials. Secret values never enter Terraform state.
API cannot write measurement evidence; workers cannot read user/session identities, delete monitors
or create schema. RDS is private/encrypted and forces TLS; application DSNs use verify-full and the
RDS CA bundle. These SQL permissions were exercised on local PostgreSQL; AWS IAM/secret replication,
network TLS, image scans and actual broker redrive remain separate live acceptance requirements.

Raw terminal jobs/results expire after the configured retention (default 90 days); old heartbeats
after 7 days. Hard monitor deletion cascades jobs/history. No response bodies are stored, but configured
URLs are persisted for execution: use token-free public health endpoints, not secret query strings.
Unexpected API/worker errors log an error type/correlation ID, not exception strings, SQL parameters,
DSNs or raw SDK messages. Infrastructure state/plans/account inputs are ignored and excluded from
Docker context. See the [operations runbook](operations.md) for destructive rollback and replay.

## Before any public launch

1. Email ownership verification, account recovery/deletion policy, session administration and abuse controls.
2. Shared rate limits/concurrency controls and a trusted ingress/proxy design. Current auth limits are
   deliberately in-memory, single-process only. Keep `--no-proxy-headers` until a trusted proxy is configured.
3. HTTPS termination, secure-cookie review, CSP review and managed production secrets.
4. Live worker egress/isolation review and security testing of the actual deployed topology.
5. Account/monitor ownership policy enforcement appropriate to an Internet-facing service.
6. Database backups and verified restoration, retention/deletion policy, operator alerts and cost budgets.
7. Load, dependency, security and deployment review. Compose is development-only, with local credentials.

The API is not a network scanner, traffic generator, arbitrary-header requester or cloud executor.
REAL configuration and measured observations are the only current product data domain. SIMULATED
and LAB tables/APIs are not created prematurely; they must remain separate when implemented. The
current staging stack and application are not a public-production security certification.

# ADR 002 — Explicit, short-lived sessions for cookie-blocked development previews

- **Date:** 2026-11-19
- **Status:** Accepted for non-production previews only

## Evidence

A user reported sign-in failure with an `HTTP_ERROR / Not Found` screenshot. Opening the API port's
root reproduced the screenshot. Separately, API logs showed successful login responses immediately
followed by protected monitor requests returning 401. Preview cookie mode was already enabled with
Secure, HttpOnly, SameSite=None and Partitioned attributes; turning it on again was not a repair.
The exact user's browser/proxy cookie-blocking mechanism could not be inspected from the sandbox.

## Decisions

1. Allow an optional `FRONTEND_DIST` build to serve the dashboard at the API's `/` entry point. Existing
   API paths and JSON error envelopes remain unchanged. Vite hot reload and the Nginx production
   topology remain available; frontend browser requests are still same-origin relative URLs.
2. Confirm `/auth/me` after login/register before rendering the authenticated dashboard. A 200 login
   does not establish that the browser accepted and returned its session cookie. Keep the form visible
   with actionable recovery if verification fails; do not silently cycle through a false dashboard.
3. Only when explicitly configured with `EMBEDDED_PREVIEW=true`, permit an explicitly opted-in
   login/register response to include a random opaque session credential. Use a custom request header
   for subsequent requests, never a URL. Keep server-side digest storage, expiry, authorization, login
   rotation and logout revocation. Default lifetime is one hour, configurable within 5–120 minutes.
4. Store that preview credential in memory and tab-scoped sessionStorage, never localStorage. Clear it
   on successful logout, expiry or rejection. Catch storage-denied errors and retain only page-lifetime
   memory state when storage is unavailable. Passwords are never put in browser storage.
5. Preserve HttpOnly cookie-only authentication outside this preview mode. Production settings reject
   the mode; production ignores the preview opt-in and credential headers. Do not relax CSRF/Origin
   checks, enable permissive CORS, seed shared credentials or reset existing accounts to hide the issue.

## Tradeoff and limitations

Preview sessions are JavaScript-readable and lose the HttpOnly cookie's resistance to same-origin
XSS token theft. This is a bounded development-only exception to ADR 001, not a recommended public
session architecture. Short expiry and tab-scoped storage reduce persistence, not XSS risk. Keep the
mode off outside trusted non-production previews. A browser that blocks both cookies and all storage
cannot retain a login across reloads; opening the preview in a normal tab is the recovery path.

## Verification

Regression tests exercise registration, protected monitor configuration, logout/revocation, existing
account login and reload with **all Cookie/Set-Cookie headers stripped**, including partitioned
cookies. Chromium loads the real built dashboard in a cross-site iframe through a controlled proxy.
Additional cases deny all storage and verify that a blocked cookie-only deployment does not display
a fake authenticated dashboard. Backend tests cover expiry, rotation, opt-in, mode isolation, tenant
isolation and unchanged CSRF checks. These reproduce adverse transport conditions; they do not claim
to instrument the user's actual Arena browser.

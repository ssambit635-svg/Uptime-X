# ADR 001 — A usable configuration slice before a monitoring engine

- **Date:** 2026-11-19
- **Status:** Accepted for Phase 1 foundation

## Context

The repository began with only the expanded PRDs. The requested first increment is approximately
30% of Phase 1. A convincing fake dashboard would not satisfy the product's evidence/provenance
principles, and running arbitrary URL requests without execution-time controls would be unsafe.

## Decisions

1. Start with a modular FastAPI monolith and React/TypeScript/Vite UI. Keep API routes, schemas,
   security policy and persistence separated. No premature microservices, Redis, AWS or lab scaffolds.
2. Implement the end-to-end **account → saved monitor → lifecycle management** journey first.
3. Use PostgreSQL as the deployment target and SQLAlchemy/Alembic from day one. Allow SQLite only
   as an explicit local/test convenience; test both engines, and test quota concurrency on PostgreSQL.
4. Use vetted Argon2id hashing and revocable server-side opaque sessions instead of localStorage JWTs.
   Registration signs in immediately for development. Email verification/recovery remain launch gates.
5. Use a same-origin browser/API topology with a custom CSRF header and Origin checks. The frontend
   uses only relative URLs; Vite and Nginx perform server-side proxying. No wildcard CORS.
6. Treat all newly configured monitors as UNKNOWN; PAUSED is a user-controlled configuration state.
   Do not create fake measurements, synthetic incidents or illustrative uptime charts.
7. Validate URL syntax and public DNS now, but explicitly postpone HTTP requests until destination
   pinning, redirects, bounded execution, persistence and controlled-network tests are implemented.
8. Use real typed API calls and server persistence, not localStorage monitor mocks or seeded accounts.
9. Introduce Docker/CI definitions now, while distinguishing configured checks from checks actually run.

## Consequences

The UI is useful for preparing monitor configuration, but cannot report website health yet. The next
slice can attach a real check pipeline without replacing identity, storage or client contracts.
Hard configuration deletion is temporary; introduce archival and retention before check history ships.
The API is a development foundation and must not be publicly launched as production-ready.

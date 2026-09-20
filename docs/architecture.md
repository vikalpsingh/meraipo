# Architecture

MeraIPO is a modular monolith. Next.js server-rendered pages call the versioned FastAPI read API. FastAPI reads Redis and PostgreSQL only. Workers own provider access; public traffic never invokes a provider. Python packages contain database models, deterministic services, and provider contracts. Separate containers are deployment roles, not microservices.

Public navigation: Home, IPO Tracker, About / Methodology. Company journeys are linked from tracker rows. Admin is hidden from navigation and independently authenticated using Argon2id and database-backed sessions.

The previous Sites/D1 prototype remains at the repository root during migration. The supported new application lives under apps/ and is started through Compose. Do not deploy it to the old Worker runtime: FastAPI, PostgreSQL and Redis require a container-capable host.

## Phases and gates
1. Bootstrap/infrastructure: configuration and tooling checks.
2. Schema/migrations: migration and constraint tests.
3. Providers: contract, missing-value, idempotency tests.
4. API: filtering, pagination, error and security integration tests.
5. Home: statuses, missing GMP, scheduled content tests.
6. Tracker: one-company rows and validated screening filters.
7. Journey: immutable baseline and historical periods.
8. Admin: authentication, CRUD, revisions, messages, ads and audit.
9. Jobs/cache: retries, import runs, invalidation and duplicate handling.
10. Security/SEO/observability: headers, metadata, sitemap, health.
11. Tests: pytest, frontend unit tests, desktop/mobile Playwright.
12. Deployment: container validation and an explicit release gate.

Each implementation phase runs the applicable automated checks; failed checks block release. No provider credentials or data licenses are assumed.

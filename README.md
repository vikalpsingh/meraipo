# MeraIPO

From IPO to Value Creator. The new modular application uses Next.js, FastAPI, PostgreSQL, Redis and Celery. The previous Sites/D1 prototype remains at the root for reference; its npm scripts and hosting configuration do not deploy this new application.

- `/`: current and upcoming IPO cards.
- `/tracker`: historical issue, listing, price-return and latest quarterly comparison.
- `/ipo/{slug}`: immutable IPO baseline, quarterly financial history and source records.
- `/meraadmin`: password/session-protected maintenance, absent from public navigation.
- `/about`, `/methodology` and trust pages explain coverage and limitations.

## Current data status
All seeded companies and figures are fictional samples. Live adapters require configured access and display rights. Provider contracts, manual/fixture ingestion, scheduled jobs, provenance and conflicts are implemented. PostgreSQL preserves GMP history and quarterly revisions; the IPO baseline is immutable. Quotes, messages and optional ads are administered through the protected console.

## Development
Requires a running Docker engine. Copy `.env.example` to `.env`, then:

```sh
docker compose up --build -d
docker compose exec api python -m packages.database.seed
docker compose exec api python -m apps.api.cli create_admin vikalp.singh@gmail.com
```

Open `http://localhost:3000` and `/meraadmin`. The CLI prompts for a password of at least 14 characters. No default admin/password is shipped. Use `reset_admin_password` to reset credentials and revoke sessions. The opt-in, idempotent seed is prohibited in production: 3 open, 3 upcoming, 10 listed and 1 closed company, with 36 quarters across six companies.

Without containers: Python 3.13, Node 24, PostgreSQL and Redis are required. Install `requirements.lock`, then `pip install --no-deps -e .`; run `npm ci` inside `apps/web`. Configure `.env`, run `python -m alembic upgrade head`, `uvicorn apps.api.main:app --reload`, and `npm run dev` inside `apps/web`. Worker/beat commands are in Compose.

## Verify before release

Install Chromium with `npx playwright install chromium` inside `apps/web`, then run `python scripts/verify.py --local` from the root. This checks Ruff, Black, shared-package MyPy, pytest, TypeScript, ESLint, Prettier, Vitest, desktop/mobile Playwright and the production web build. Local API/browser tests use disposable SQLite databases.

For release, set `TEST_DATABASE_URL` to an isolated PostgreSQL database named **meraipo_test**, configure Redis, and run `python scripts/verify.py` without `--local`. This additionally checks actual infrastructure and migrations. Tests delete data in the isolated test database; never point them at an application database. CI also builds the containers. Staging smoke tests and exact image promotion are required; CI does not deploy automatically.

## Repository and documentation

```text
apps/web/                 Next.js UI, Vitest and Playwright
apps/api/                 FastAPI, validation, sessions, maintenance and CLI
apps/worker/              Celery schedules and ingestion
packages/database/       SQLAlchemy models, Alembic and demo seed
packages/shared/         Configuration and financial calculations
packages/providers/      Contracts, adapters and document storage
infrastructure/          Non-root container images
tests/                   Python unit/API/provider/infrastructure checks
scripts/verify.py         Local and fail-closed release gates
docs/                    Architecture, security, API and deployment
```

See [.env.example](.env.example) for configuration. Production requires `ENVIRONMENT=production`, both demo flags false, HTTPS origin/site URL, non-default PostgreSQL credentials and shared Redis. The web demo flag, site URL and API rewrites are build-time configuration: rebuild when changing them.

- [Architecture](docs/architecture.md), [data model](docs/data-model.md), [API](docs/api.md)
- [Providers](docs/provider-design.md), [security](docs/security.md), [scaling](docs/scaling.md)
- [Deployment and backups](docs/deployment.md), [implementation/release status](docs/implementation-status.md)
- [Applicant features and guide maintenance](docs/applicant-experience.md)
- [Market integration, scheduler setup and deployment](docs/market-data.md)
- [Data integration test coverage](docs/market-data-tests.md)

The current upgrade has not been deployed to the previous live prototype.

The staged exchange collector/publisher workflow and current source readiness are documented in [docs/exchange-pipeline.md](docs/exchange-pipeline.md).

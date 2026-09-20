# Implementation and release status

The new application is local, not a replacement deployment of the previous Sites prototype. Git remote: `https://github.com/vikalpsingh/meraipo.git`. No new changes have been pushed by this task.

Implemented: public pages and SEO; normalized database/migration; calculations, provenance and conflicts; sessions/CSRF/rate limits; admin IPOs, quarterly revisions/imports, GMP, scheduled messages/quotes, ads and audit; manual/fixture ingestion, price-history snapshots and document storage; Celery schedules/retries; Redis invalidation; Compose and CI release gates.

## Market integration update (20 September 2026)

Added protected Vercel cron forwarding, durable market jobs, database leases, pause/manual/scoped/backfill controls in MeraAdmin, provider setup/health, versioned approved-feed contracts, bounded HTTP retry, raw payload retention, subscription deduplication, same-source EOD corrections, financial revisions, annual history and strict configurable XBRL parsing. The public journey displays the latest eight quarters and four annual years, with matching-basis comparisons and financial-sector metrics. See the [complete A–M integration and deployment report](market-data.md).

The latest full Python run passed 77 tests. Frontend unit/route tests passed 28 tests. All 24 desktop/mobile browser tests passed, including imported-data views and uncaught JavaScript/hydration checks. TypeScript, ESLint, formatting, MyPy, the Next.js production build, SQLite migration preservation/model comparison, PostgreSQL migration SQL generation and Compose configuration validation passed. See the [test coverage report](market-data-tests.md).

No live data feed is connected yet. Approved endpoints, provider-specific contract mapping and credentials are still required. The current boundary is executable and fixture-tested; it is not a claim of native NSE/BSE/InvestorGain connectivity. Docker's engine remains unavailable, so live PostgreSQL/Redis worker tests remain a release gate.

## Verification (19 September 2026)

After adding the applicant experience: 55 backend cases passed in the full suite, plus the new migration-preservation test passed separately (56 distinct cases). All 24 frontend unit/component tests and all 14 desktop/mobile Playwright cases passed. TypeScript, ESLint, Prettier, Ruff, Black and shared-package MyPy checks passed. The Next.js production build passed. The guide migration upgrades an existing database without changing IPO values, matches the models, and supports downgrade/re-upgrade in SQLite. PostgreSQL migration SQL also generates successfully; this does not prove a running PostgreSQL migration. Browser runs shut down correctly with normal Windows process permissions.

Features 1–6 are implemented: India-time next-action strip, issue/category-specific amount calculator, sourced timeline and calendar download, verified registrar links, personal application checklist, and admin-maintained company brief. See [applicant experience](applicant-experience.md) for configuration and exact behaviour.

## Release limitations

- Docker Desktop's engine was unavailable during local verification. PostgreSQL/Redis migrations, workers, cache and container integration must pass in CI or a working Docker environment. SQLite tests do not substitute for these.
- Live adapters, real financial data and display rights need configuration. Seed data is fictional, visibly labelled and prohibited in production.
- Provision `vikalp.singh@gmail.com` through the interactive CLI against the intended database. No password has been invented or stored.
- Document storage/ingestion is implemented in the backend; PDF upload/extraction UI is not. Bulk quarter import accepts JSON.
- Annual and subscription ingestion are implemented through the approved-feed boundary. Native provider mappings, peer/valuation synchronization and corporate-action adjustment remain. Price highs describe available recorded history, which may be incomplete.
- Trends are computed from stored quarters at read time. Persisted snapshots/incremental aggregation are future scaling work. Catalog filtering currently operates on a bulk-loaded catalog; use database filtering/materialized summaries as coverage grows.
- MFA, external penetration testing, centralized alert delivery and backup restore drills remain deployment work.
- Review legal/operator-contact text and retention policy before publishing. Configure production secrets, backups, branch protection and environment approvals outside this repository.

## V2

Licensed live adapters and corporate-action normalization; filing extraction/review queue; conflict-resolution UI; CSV import preview; materialized screening summaries; annual/peer analysis; consent-based watchlists; MFA and operational alerting.

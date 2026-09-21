# Market data integration and scheduler

For the current direct-exchange jobs, staging-to-master flow, and 23:00 IST schedule, see [Exchange pipeline](exchange-pipeline.md). The feed contract and legacy jobs below remain available as optional integration tools.

## A. Architecture and current status

The existing Next.js App Router frontend, FastAPI API, SQLAlchemy/Alembic database and Celery/Redis worker are retained. No Supabase client or duplicate company database was introduced. Vercel serves the web application from `apps/web`; the Python API and worker must run on a separate container-capable service with PostgreSQL and Redis.

Vercel GET cron → server-only authorization → FastAPI authenticated enqueue → durable `data_import_runs` row → Celery worker → database lease → configured bulk feed → Pydantic normalization → per-record savepoint → existing database tables → public API/cache. Public requests never fetch providers.

**Live exchange/vendor access is not configured or verified.** The working integration boundary accepts the documented versioned JSON feed below. A licensed provider or an approved exchange gateway must supply this contract. This is not a claim that arbitrary native NSE/BSE/vendor JSON can be connected merely by adding a key. Native responses require an adapter mapping to this contract. There is no CAPTCHA bypass, browser-cookie scraping, or invented live data.

## B–C. Implementation inventory

New code:

- `packages/providers/market.py`: validated feed contracts, bounded HTTP client, retry and normalization.
- `packages/providers/xbrl.py`: strict context/unit-aware XBRL instance parser with explicitly reviewed concept mappings.
- `apps/worker/market.py`: lifecycle, identifier matching, snapshot/revision persistence, DB lease, orchestration and run history.
- `apps/worker/market_cli.py`: command-line enqueue into the same workflow.
- `apps/api/market_routes.py`: cron authentication, admin setup/status/pause/manual/backfill API.
- `packages/shared/market_freshness.py`: event/trading-day-aware source status.
- `apps/web/app/api/cron/[job]/route.ts`, `apps/web/vercel.json`: protected scheduler bridge and UTC schedules.
- `apps/web/components/market-console.tsx`, `market-data.tsx`: admin controls and public subscription/GMP/annual views.
- `tests/test_market_integration.py`, `apps/web/tests/e2e/market.spec.ts`: deterministic ingestion and browser checks.

Extended existing models, repository, worker task configuration, API registration, frontend types/company journey/admin console/styles, `.env.example`, Compose environment and migration regression fixture. Earlier applicant flows and administrator authentication remain in place.

## D. Migration

`626a25f2c463_market_data_scheduler`, following `20260920_applicant_guides`:

- Adds company type and unique nullable ISIN.
- Extends IPO source/lifecycle, subscription snapshot metadata, GMP provenance, EOD OHLC/volume/turnover, quarterly/annual filing metadata, and existing import runs.
- Adds raw payloads, expiring job leases, scheduler pause controls and item errors.
- Replaces annual company/year uniqueness with company/year/revision uniqueness so corrections preserve history.

Run `python -m alembic upgrade head` once before API/worker rollout, then `python -m alembic check`. Back up first. Roll back application images instead of dropping historical data. A down-migration to the old annual uniqueness cannot succeed when multiple revisions exist; archive/review such records before any intentional schema rollback.

Subscription categories are stored as decimal **strings** in JSON, validated as Decimal, not floating-point authoritative values; the total multiple retains the existing Numeric column. Original financial metrics remain Numeric; industry-specific metrics also use validated decimal strings. API display converts values for presentation only.

## E. Environment and setup

| Setting | Where | Purpose |
|---|---|---|
| `CRON_SECRET` | Vercel + API | Same random secret, at least 32 characters; never `NEXT_PUBLIC_*` |
| `API_INTERNAL_URL` | Vercel | Reachable HTTPS origin for the separately deployed FastAPI service |
| `MARKET_FEEDS_JSON` | API + worker | Private feed configuration, including bearer tokens |
| `MARKET_SCHEDULER_ENABLED` | API + worker | Default false; true enables cron dispatch and disables legacy Celery beat schedules |
| `TRADING_CALENDAR_YEAR` | API + worker | Confirmed exchange calendar year; EOD fails closed when it is not the current year |
| `TRADING_HOLIDAYS` | API + worker | Comma-separated `YYYY-MM-DD` exchange holidays; update annually |
| `DATABASE_URL`, `REDIS_URL` | API + worker | Existing managed Postgres and shared Redis settings |
| `PUBLIC_ORIGIN`, `SITE_URL` | API / web | Exact HTTPS web origin for cookies, CSRF and canonical URLs |

Admin → **Data & scheduler** shows readiness without exposing credentials. Configured settings do not prove connectivity. Observe a completed run and saved records before treating a feed as operational. Pause controls are persisted and apply to manual and scheduled runs; resume before running manually.

Configuration example (use real approved endpoints, store securely; JSON on one line in an env file):

```json
{
  "ipos": {"nse-approved": {"enabled": true, "authority": "NSE", "url": "https://your-approved-gateway.example/ipos", "token": "REPLACE_SECURELY"}},
  "subscriptions": {"nse-approved": {"enabled": true, "authority": "NSE", "url": "https://your-approved-gateway.example/subscriptions", "token": "REPLACE_SECURELY"}},
  "gmp": {"licensed-gmp": {"enabled": false, "authority": "UNOFFICIAL", "url": "https://your-licensed-feed.example/gmp", "token": "REPLACE_SECURELY"}},
  "prices": {"licensed-eod": {"enabled": true, "authority": "LICENSED", "url": "https://your-licensed-feed.example/eod", "token": "REPLACE_SECURELY"}},
  "results": {"nse-approved": {"enabled": true, "authority": "NSE", "url": "https://your-approved-gateway.example/results", "token": "REPLACE_SECURELY"}}
}
```

Multiple configured exchange sources are visited NSE first, then BSE, then provider name. Existing differing authoritative values are held as conflicts rather than silently replaced. Same-source newer observations can update data; older filings cannot supersede newer ones. Manual/other-source financial records require reconciliation before automatic replacement.

## F. Schedules

| Job | UTC cron | IST |
|---|---|---|
| IPO master | `30 1 * * *` | 07:00 daily |
| Live IPO | `0 5,7,9,12 * * *` | 10:30, 12:30, 14:30, 17:30 daily |
| Live IPO extra | `30 10 * * *` | 16:00 daily |
| EOD | `45 12 * * 1-5` | 18:15 weekdays; worker also checks holiday calendar |
| Results | `30 13 * * *` | 19:00 daily |
| Reconcile | `0 17 * * *` | 22:30 daily |

Vercel runs production deployment cron jobs. The multiple-times-per-day expression requires a suitable paid plan; Hobby only supports daily frequency and less precise timing. See [Vercel cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing) and [cron security/concurrency](https://vercel.com/docs/cron-jobs/manage-cron-jobs). Do not run another scheduler for the same feeds.

`ipo-live` checks the database before contacting providers. No non-demo OPEN IPO means SKIPPED. EOD skips weekends/confirmed holidays and marks missing current-day data SOURCE_NOT_READY. Reconcile retries configured feeds and derives lifecycle. A missing optional GMP feed is shown explicitly; manual GMP remains available.

## G. Feed and financial contracts

All endpoints receive GET with `from` and `to` ISO dates, plus optional `company_id` for scoped requests. Return a bounded bulk response:

```json
{"schema":"meraipo-feed-v1","records":[
  {"isin":"INE000A01010","source_url":"https://exchange.example/original-filing","source_timestamp":"2026-07-20T10:00:00Z","price_date":"2026-07-20","close":"130.00","open":"126.00","high":"135.00","low":"125.00","volume":"10000"}
]}
```

This is a **fictional fixture**, not market information. Common identity fields are `isin`, `nse_symbol`, `bse_code`; at least one is required. Two identifiers pointing to different companies cause a conflict. Names are never used to match existing companies. Nontracked securities in bulk feeds are ignored. Known demo companies are excluded from automatic observations.

Kind-specific records (see Pydantic models for the exact schema):

- **ipos:** common observation + `official_status`, `company_type`, and `issue` containing the existing IPO input (slug/name/sector/status/price band/lot/dates/source URL). Identity is supplied outside `issue`. Existing original IPO baseline is immutable.
- **subscriptions:** common observation + `categories`, keyed by `qib`, `nii`, `bnii`, `snii`, `retail`, `employee`, `shareholder`, `total`; each supports nullable `multiple`, `bid_shares`, `offered_shares`. Changed category values create snapshots; identical values do not.
- **gmp:** common observation + decimal-string `value`. Stored as unofficial. Display percent is value/upper band ×100; implied price is upper band+value. No guaranteed-return language.
- **prices:** example above; optional previous_close/turnover. One company/date row, same-source newer correction updates it; last-good prices retained on errors. Bulk responses are restricted locally to tracked listed companies and the requested current EOD date.
- **results:** common observation + `financial_year` (ending March year), `period_type` QUARTERLY/ANNUAL, `quarter` 1–4 or null for annual, `statement_type` CONSOLIDATED/STANDALONE, `period_start`, `period_end`, `filing_id`, `currency: INR`, `unit: INR_CRORE`. Existing revenue/EBITDA/PAT/EPS/etc fields are optional. `industry_metrics` supports total_income, other_income, net_interest_income, operating_profit, aum, gnpa, nnpa, finance_cost, depreciation, pbt, tax. EPS is rupees; GNPA/NNPA are percentage points. Never invent missing metrics.

Results reject year-to-date numbers masquerading as discrete quarters. Public display prefers consolidated, preserves revisions, compares matching bases only, and uses null for missing/nonpositive comparison bases. Margin differences are computed in basis points. Annual and pre-IPO restated baseline records remain distinct. Financial result freshness is event-driven: a quiet day with no new filings is not stale financial data.

XBRL variant: an approved results gateway can include `xbrl` (instance XML) and `context_id` instead of normalized metrics/period dates. Configure `xbrl_concepts` as metric → **expanded XML QName**, e.g. `"revenue":"{https://your-reviewed-taxonomy.example/2026}RevenueFromOperations"`. Map the exact official taxonomy/version for each feed. Parser validates contexts, reporting duration, INR units and EPS per-share units, rejects entity declarations/ambiguous duplicate facts/segment contexts, and converts INR amounts to crore. Ratios with uncertain XBRL scaling are rejected for review. This is **not** an automatically verified mapping for every NSE/BSE industry taxonomy or inline-XBRL document. Keep normalized JSON as the integration boundary for unsupported taxonomies. [NSE taxonomy resources](https://www.nseindia.com/static/companies-listing/xbrl-information) and [NSE data usage policy](https://www.nseindia.com/static/market-data/nse-data-policy) govern onboarding.

HTTP behavior: HTTPS endpoints, header-only credentials, no redirects, 20-second request timeout, maximum 5 MB/5,000 records, bounded 2/5/15-second+jitter retries on network/429/5xx, Retry-After respected within a 30-second bound. Longer Retry-After requests are deferred to a later run. No retries for 400/401/403/schema errors. Raw successful feed payloads are retained with provider, hash, URL without query, HTTP status and parser version; malformed JSON envelopes are retained with a job error. Bad individual normalized records retain the original envelope for inspection.

## H–I. Verification and commands

```text
python -m pytest -q
python -m ruff check apps/api apps/worker packages tests
python -m black --check apps/api apps/worker packages tests
python -m mypy
cd apps/web
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js .
node node_modules/vitest/vitest.mjs run
node node_modules/@playwright/test/cli.js test
node node_modules/next/dist/bin/next build
```

Tests use deterministic fictional data, HTTP mock transports and local test databases. They cover lifecycle, no-open skip, item isolation, deduplication, EOD returns, consolidated revisions, annual limits, lease expiry/overlap, HTTP retries, cron/admin authorization and desktop/mobile scheduler controls. The migration regression creates the old schema, inserts an old IPO, upgrades/checks/downgrades/reupgrades while preserving the IPO.

Local validation is not a replacement for PostgreSQL/Redis worker validation. The Docker engine was unavailable during this implementation. Before release run the existing full `scripts/verify.py` against isolated PostgreSQL/Redis (database name `meraipo_test`), and exercise worker kill/restart and overlapping cron requests on staging. See the implementation report for final local test counts.

## J. Deployment sequence

1. Obtain approved/licensed feed access and verify each adapter contract against recorded responses. Keep GMP disabled until permitted access exists.
2. Provision managed Postgres/Redis and a container host for FastAPI/Celery. Apply migration with a backed-up database. Configure private environment consistently for API/worker. Use an outbound host allowlist at infrastructure level.
3. Create the admin with `python -m apps.api.cli create_admin vikalp.singh@gmail.com`; password is prompted, never passed in shell history.
4. Deploy web from Vercel root directory `apps/web`. Set server-only `API_INTERNAL_URL`, `CRON_SECRET`, plus production origin/site settings and disable demo mode. Vercel uses `apps/web/vercel.json`.
5. Ensure API is reachable over TLS from Vercel and web-origin admin cookies/CSRF work through `/api/v1` rewrites. Never expose Postgres/Redis publicly.
6. Start `celery -A apps.worker.tasks.celery worker --loglevel=INFO --concurrency=2`. Keep the container running. Vercel does not host this worker. Stop legacy beat or enable market scheduling consistently so legacy schedules are empty.
7. Validate readiness, manually import a small real company, inspect counts/source/values, then set MARKET_SCHEDULER_ENABLED=true and redeploy/restart.
8. Confirm Vercel cron entries are enabled on the production deployment. Test missing/bad authorization (401), proper enqueue (202), completed DB job, and refreshed public data.

If hosted on Supabase Postgres, use a private server database role. This application does not use browser Supabase access; do not grant anon/authenticated roles access to raw payloads, admin sessions, audit logs, job controls or writes. Disable exposed Data API schemas or revoke table grants and add RLS appropriate to your deployment before exposing Supabase APIs. Existing server-only architecture does not automatically configure an external Supabase project.

## K. Manual verification

- At the next 07:00 IST schedule: confirm Vercel invoked ipo-master, API accepted it, worker finished, and admin displays its start/end/status/counts. Compare one imported issue against the approved source; no fixture should appear as live data.
- Open IPO: subscription update creates one snapshot; repeat unchanged payload creates none. GMP stays labelled unofficial.
- No open IPO: live job skips with zero external requests.
- Listing date: lifecycle becomes LISTING_TODAY/LISTED and EOD tracking begins.
- Trading holiday: EOD is NOT_EXPECTED and last good price remains.
- Results: new quarterly/annual filing appears, revision preserves original, and missing comparison quarters show a dash.
- Duplicate run: only one market writer holds the DB lease. Worker hard kill releases the lease after six minutes; stale queued/running history is marked failed after ten minutes when admin status is read.
- Provider outage: job FAILED/PARTIAL with error; previous public data remains intact. Fix provider, then use Run now or the evening reconciliation.

CLI examples (same queue/orchestrator as admin):

```text
python -m apps.worker.market_cli ipo-master
python -m apps.worker.market_cli results --company-id COMPANY_UUID
python -m apps.worker.market_cli backfill --company-id COMPANY_UUID --from-date 2025-04-01 --to-date 2026-03-31 --confirm-backfill
```

Backfill is durable **one company / at most 366 days per submitted job**. Queue consecutive years to obtain four annual years/eight quarters or prices since IPO; requests are not an unbounded in-memory all-company scan. A failed chunk can be repeated safely. Automatic multi-year fan-out and pagination/cursor continuation are future extensions, not implemented claims.

## L. Known limits

- No live vendor credentials, permissions or provider-specific native JSON mappings have been validated; no production deployment was made.
- Raw XML requires reviewed concept mappings. Nonstandard financial year ends, segment results, inline XBRL, PDFs and automatic annual-minus-nine-month derivation are intentionally not inferred.
- IPO quota, lead-manager and anchor/allotment/refund/demat dates are stored when supplied; the public applicant guide still requires reviewed application guidance. Missing data is shown as unavailable.
- Holidays are an operator-maintained confirmed calendar; special weekend sessions require a future trading-session calendar extension.
- Source conflicts are reported and held; comprehensive conflict-resolution/mapping editors and automatic precedence reassignment are not yet provided.
- Bounded JSON envelopes, including invalid-schema responses, retain raw payloads. No large-object spillover/retention policy is implemented; enforce the 5 MB bound and database retention operationally.
- Job status covers queue dispatch and worker results, not a continuous worker heartbeat. Queue failures are recorded; orphaned messages require manual retry. No unsolicited external alert channel is configured.
- Backfills are bounded manual chunks, not automatic four-year pagination. Feed gateways must honor the documented date contract; local observations are also range-filtered.
- PostgreSQL/container integration and live-provider staging tests are required before release.

## M. Next improvements

Prioritize onboarding one approved exchange feed and one licensed EOD source with real fixtures, then staging PostgreSQL/Redis failure testing. Add provider-specific taxonomy maps, worker heartbeat/alerts, cursor-based backfill automation, a reviewed conflict-resolution workflow and an official trading-session calendar. Keep the public interface focused on application dates, verified facts and readable financial history.

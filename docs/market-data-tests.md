# Data integration regression coverage

The suite uses fictional records and mock HTTP transports. Browser fixtures pass through the real normalized persistence functions into a disposable migrated database; public requests read that database through FastAPI. Tests do not connect to exchange websites or licensed providers. Test bootstrap explicitly disables configured market feeds and cron execution.

## Coverage

| User/data scenario | Automated evidence |
|---|---|
| New issue discovery, identifier creation, same-source update | `test_discovery_update_listing_and_conflict` |
| Dates advance through opening/allotment/listing | Six `test_ist_lifecycle` cases |
| No active IPO means no provider request | `test_no_open_skips_before_provider` |
| Subscription deduplication and one malformed item among valid items | `test_snapshot_dedup_and_item_isolation` |
| GMP history and implied price remain consistent | `test_gmp_and_eod_retain_history` |
| EOD import is idempotent and changes IPO returns | Same test plus imported-data browser checks |
| Original and corrected results retained, consolidated preferred | `test_revisions_consolidated_and_safe_comparisons` |
| Missing comparable quarter returns null | Same test plus missing-comparison browser check |
| Latest eight quarters, newest first | Real-import browser fixture with ten stored periods |
| Latest four annual years, newest first | `test_annual_history_four_years_and_revisions` plus browser fixture with five stored years |
| Bank layout avoids forced EBITDA/revenue template | Imported bank browser fixture |
| Provider outage preserves last good data | `test_provider_failure_preserves_last_good` |
| Malformed response remains traceable | `test_malformed_envelope_retained` |
| Duplicate writer is excluded; expired lease recoverable | `test_lock_expiry_and_overlap` |
| Retry transient 429; fail fast on 403 | `test_feed_retry_and_no_credentials_in_errors` |
| Unsafe XML, incorrect units, YTD-as-quarter rejected | XBRL/financial tests |
| Trading-day and event-driven source freshness | `test_trading_day_and_event_freshness` |
| Cron rejects unauthenticated requests; authorized request queues | Python API test, Next route unit tests and browser 401 checks |
| Admin requires session/CSRF, pause/resume persists | API tests and desktop/mobile scheduler test |
| Backfill requires confirmation/company/date bounds | `test_cron_dispatch_and_backfill_bounds` |
| Existing data survives schema upgrade | Migration preservation test with upgrade/check/downgrade/re-upgrade |
| Existing quote editor, guides, calculator, search and navigation work | Existing critical desktop/mobile regression suite |

## Commands and release gate

From the repository root, run `python scripts/verify.py --local` for Python checks/tests, frontend type/lint/format/unit checks, Playwright and production build. This does not qualify as a production release check.

Run `python scripts/verify.py` with a working Redis service and `TEST_DATABASE_URL` pointing to an isolated PostgreSQL database named `meraipo_test` before release. It fails closed if infrastructure is missing. Never use the production database for destructive fixture tests.

The latest complete Python run passed **77 tests**. Frontend unit and cron-route tests passed **28 tests**. TypeScript, ESLint, Prettier, Ruff, Black and MyPy passed; Next.js production build passed. SQLite migration preservation and PostgreSQL migration SQL generation passed. Docker Compose configuration validated, but the Docker engine was unavailable for live PostgreSQL/Redis/worker checks.

The final full Playwright run passed **24 desktop/mobile tests**, including automatic checks for uncaught JavaScript and hydration errors. Imported-data tests read ten stored quarters and five annual years and verify the public eight-quarter/four-year defaults. Scheduler screenshots were visually reviewed on desktop and mobile. The targeted market/migration rerun passed 22 cases after the final correction-handling changes.

Tests cannot prove compatibility with unconfigured provider schemas or production network behaviour; replay approved real response fixtures and exercise queue/cache/worker failure cases on staging before release.

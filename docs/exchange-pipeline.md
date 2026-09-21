# MeraIPO exchange pipeline

Each scheduled job downloads into durable staging and then publishes validated records to the existing master tables **in the same worker execution**. The public UI reads those masters. Failed downloads do not erase previously published values, and a failed publishing phase leaves staging available for retry.

## Schedule: Asia/Kolkata

| Job | Time IST |
| --- | --- |
| `sync-ipos` — IPO, subscription and configured unofficial GMP | Daily 23:00 |
| `sync-prices` — daily NSE/BSE closing prices | Trading weekdays 23:10 |
| `sync-results` — quarterly and annual financial filings | Friday 21:00 |

23:00 supersedes the earlier 01:00 request. The price offset avoids overlapping writers; results retain the requested Friday 21:00 timing. Standalone collect/publish jobs remain available under advanced admin tools for troubleshooting.

## Architecture

1. Bounded official downloads are retained in `data_raw_payloads` with provenance.
2. Validated observations enter `market_staging`, deduplicated by source and content. Collection does not alter public masters.
3. The same sync job commits staging, then publishes under the shared database writer lease. Admin counts distinguish staged and published records.
4. Existing IPO, subscription, GMP, price and financial masters power the public API. Cache invalidation follows successful database commits.

`exchange_price_history` has a unique company/date/exchange key and stores normalized OHLCV from both exchanges. `market_prices_eod` is the canonical public close: NSE preferred, BSE fallback. Official trading after an IPO's closing date can confirm listing; the original listing date and price are never invented from a later price observation.

`company_subscription_days` uniquely identifies company/date/exchange and references the latest intraday snapshot. `company_subscription_details` joins category rows containing bid shares, offered shares and multiple. Intraday changes replace the day's summary; a new date retains a new daily row. The original snapshot history remains available.

The API takes NSE total subscription and BSE category values from the latest observed day. It retains category-level source and timestamp, never adds exchange totals, and flags disagreement greater than 0.01×. Old-day categories are not silently combined with a newer total. Displayed subscription percentage is `multiple × 100`, not an allotment probability or allocation quota. Missing values remain missing.

## Actual source readiness

- **NSE IPO:** built-in current-issue API and `/api/all-upcoming-issues?category=ipo`, verified from NSE's official `upcoming-ipo.js`. The latter contains active and forthcoming issues; lifecycle is determined by dates rather than treating every returned row as upcoming. BSE-flagged rows retain exact symbols under the separate `BSE_SYMBOL` identifier namespace and retain BSE subscription provenance through the NSE source. They are never assigned fabricated NSE tickers or numeric BSE scrip codes. Numeric BSE code/ISIN enrichment is still required for their price matching. EQ maps to Mainboard; SME maps to SME. Lot sizes are imported when supplied.
- **NSE/BSE prices:** bounded UDiFF CSV/ZIP parsers; one file per exchange filtered by exact tracked identifiers. Wrong dates, malformed prices, schema changes, denied requests and archive limits produce explicit failures.
- **BSE categories:** cumulative-demand HTML adapter with explicit BSE issue ID to company identifier mapping. Requires a cumulative-demand page, offered/bid-share columns and coherent ratios. Synthetic HTML tests pass; live page access was denied and actual markup compatibility remains unverified.
- **Quarterly results:** native JSON discovery and strict XBRL processing are implemented and fixture-tested. Current NSE/BSE discovery field and taxonomy mappings still require verification. No working native financial source is configured by default.
- **GMP:** exchanges do not publish it. Existing admin entry and configured unofficial feeds are supported. No InvestorGain scraper or automatic GMP source has been claimed or configured.

Initial host requests timed out on NSE and were denied by BSE. The subsequent Docker verification on September 20, 2026 reached NSE successfully: two IPO masters and two subscription masters were published, with all four staging records marked `PUBLISHED`. An existing-database upgrade defect was fixed by the forward `20260920_subscription_source` migration, and retained subscriptions were successfully retried. Three mirrored BSE issues were rejected for missing authoritative identifiers; the upcoming-issues endpoint returned 404.

The September 18 price replay downloaded and parsed NSE's file but found no prices for the two tracked IPOs; BSE's file returned 404. No daily prices were published. `sync-results` reported `SOURCE_CONFIGURATION_REQUIRED` and published nothing. These partial results are visible in admin. Access controls are not bypassed. The subsequent IPO connector correction addresses the old upcoming-URL and BSE-symbol rejections; previous error records remain as historical diagnostics.

The bottom of every authenticated admin tab contains a job error log. Its protected endpoint joins the latest 50 errors to their run ID, job and status, with IST timestamps, source/record details and remediation guidance. It refreshes every 15 seconds and supports manual refresh. SQL statements, credentials and raw exception bodies are not exposed.

The corrected live IPO run `c56db71f-dfff-4ddc-8d7c-1703b923bcda` completed `SUCCESS` with zero errors: 14 source records staged, 12 master writes, two unchanged observations, and seven distinct companies (five active, two upcoming). All five active companies have subscription totals. The two upcoming companies are Varmora Granito and Pooja Logistics. Import counters count records, not companies. The exact source response shapes are covered by `tests/fixtures/nse-ipo-snapshot.json` and the repeated-run population test.

## Docker setup

Preserve the existing `.env`. Relevant settings:

```dotenv
EXCHANGE_DIRECT_ENABLED=true
MARKET_SCHEDULER_ENABLED=true
MARKET_SCHEDULER_DRIVER=celery
EXCHANGE_SOURCES_JSON=[]
BSE_IPO_ISSUES_JSON=[]
TRADING_CALENDAR_YEAR=2026
TRADING_HOLIDAYS=<confirmed comma-separated exchange holiday dates>
```

Do not copy the holiday placeholder. Missing/outdated calendar configuration blocks price collection. `MARKET_SCHEDULER_DRIVER=vercel` disables Docker beat and permits the authenticated Vercel bridge instead; use only one scheduler owner. Vercel UTC schedules are committed in `apps/web/vercel.json`.

```powershell
cd C:\Coding\meraipo
docker compose up --build -d
docker compose exec api python -m apps.worker.market_cli sync-ipos
docker compose exec api python -m apps.worker.market_cli sync-prices
docker compose exec api python -m apps.worker.market_cli sync-results
```

Open `http://localhost:3000/meraadmin` → **Data & scheduler** to run, pause or inspect jobs. Sync jobs need no second publishing click. Rejected staging records can be retried after correcting mappings. A manual price replay accepts `--to-date YYYY-MM-DD` for one non-future trading date.

## BSE and financial mappings

BSE IPO discovery is now attempted on every direct IPO sync through the official site's `GetPublicIssue_par_updated/w?flag=1` service. The URL and field bindings were inspected in BSE's public application bundle and `assets/data/appConfig.json`. The parser handles the full `Table` array, filters known non-IPO issue types, validates platform/dates/price bands, and records bad rows with issue ID/name. It does not infer missing financial fields. New BSE-only issues use stable BSE issue IDs and any supplied BSE symbol/code/ISIN. A shared verified identifier links an existing company; an ambiguous name/symbol candidate is rejected for mapping review rather than duplicated or merged by name.

**Live access remains blocked:** this environment's requests to the BSE public API returned redirects to a member-access page; direct browser retrieval was also denied. The connector reports `BSE_ACCESS_REDIRECT` with the source URL and guidance in the admin error log and allows successful NSE records to publish. Synthetic population tests validate the published field contract, not a successful live BSE-only import. Actual BSE payload compatibility and permitted access still need verification.

`BSE_IPO_ISSUES_JSON` is an array of `{ "issue_id": "<official BSE issue ID>", "isin": "<company ISIN>" }`. An exact `nse_symbol` or six-digit `bse_code` can replace ISIN. The example issue ID in the supplied brief must not be assigned to an unrelated company. Only tracked open/closed IPOs are requested.

Each `EXCHANGE_SOURCES_JSON` entry has `name`, `exchange` (`NSE`/`BSE`), `kind` (`ipos`/`subscriptions`/`results`), official HTTPS `url`, `records_path` (dot-separated JSON path or empty for a top-level array), and `fields` mapping normalized targets to native field paths. Nested targets such as `issue.name` are supported. `defaults` can supply fixed metadata, never fabricated market values. Optional `params` expand `{from}`/`{to}` to DD-MM-YYYY; `page_param`, `size_param` and `page_size` control bounded pagination.

Financial discovery maps an exact identifier, `xbrl_url`, `source_timestamp`, and optionally `filing_id`. `concepts` maps metric names to exact expanded XML QNames (`{namespace}Concept`) for a reviewed taxonomy. Naive exchange timestamps are interpreted as IST. Actual XML instances are required; inline XBRL HTML is not supported.

Financial scans overlap fourteen days, filter tracked companies before downloading XML, skip processed filing ID/timestamp pairs and preserve revised filings. Each run is limited to five pages, twenty filings and a bounded collection time. Limits are reported; no truncated scan is presented as complete. A longer outage needs backfill. Complete fiscal quarters/annual periods, company ISIN, INR units and reporting basis are validated; ambiguous, segment/YTD, unsafe or unmapped facts are rejected. Consolidated results remain the preferred public view.

## Sources and verification

- [NSE IPO source](https://www.nseindia.com/api/ipo-current-issue)
- [NSE UDiFF reports](https://www.nseindia.com/all-reports)
- [BSE cumulative-demand example](https://www.bseindia.com/markets/publicIssues/CummDemandSchedule.aspx?ID=7154&status=L)
- [NSE financial filings](https://www.nseindia.com/companies-listing/corporate-filings-financial-results)
- [NSE taxonomy information](https://www.nseindia.com/static/companies-listing/xbrl-information)
- [NSE capital-market holiday response](https://www.nseindia.com/api/holiday-master?type=trading), verified for 2026 including January 15. Special weekend/Muhurat sessions need manual replay.

Public availability and redistribution permission are separate, as noted in the supplied brief; this implementation does not grant exchange display rights.

`tests/test_exchange_pipeline.py` covers single-job staging/publication, repeated runs, source failure isolation, NSE preference/BSE fallback, daily subscription joins, exchange-total comparisons, BSE HTML parsing, financial XML ingestion, scheduling and rejected-record recovery. Migration tests preserve existing IPO data and check schema/model agreement. Desktop/mobile Playwright tests cover the company popup, daily history, percentage display, error recovery, keyboard focus, navigation and admin controls. Fixture data stays isolated from the Docker application database.

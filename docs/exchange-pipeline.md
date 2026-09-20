# Exchange collection and publication

MeraIPO now separates downloading source data from updating the public tables. This is an end-of-day research pipeline, not a real-time quote service.

## Schedule (Asia/Kolkata)

| Collection | Time | Publication | Time |
| --- | --- | --- | --- |
| `collect-ipos` | Daily 07:00 | `publish-ipos` | Daily 07:15 |
| `collect-prices` | Trading weekdays 18:45 | `publish-prices` | Trading weekdays 19:00 |
| `collect-results` | Friday 21:00 | `publish-results` | Friday 21:30 |

Docker's Celery beat is the default scheduler. `MARKET_SCHEDULER_DRIVER=vercel` disables beat and allows the authenticated Vercel cron bridge instead. Use one scheduler owner. Legacy feed jobs remain available for manual use, under the admin advanced toggle; they are not scheduled automatically.

## Storage and guarantees

1. Download bounded source files without bypassing access restrictions. Retain raw CSV/JSON/XML and source provenance.
2. Validate exact identifiers, timestamps, financial periods, units, and source schema. Put valid observations in `market_staging`; record rejected source records in the job error log.
3. A separate publishing job writes existing IPO, financial, price, and GMP masters through the existing validated ingestion code. Only then invalidate the public cache. The shared database lease prevents overlapping writers.
4. Repeated collection and publication are idempotent. Failed sources preserve previously published data. Admin shows pending/published/rejected counts and explicit retry controls for rejected staged records after mapping corrections.

`exchange_price_history` has a unique company/date/exchange key and stores each exchange's normalized OHLCV observation. `market_prices_eod` remains the canonical public daily close: NSE first, BSE fallback. Both raw observations remain available. An official close can confirm that an existing IPO has listed after its closing date; it does not fabricate the original listing date or listing price.

`company_subscription_days` has a unique company/date/exchange key and links to its latest intraday `ipo_subscriptions` observation. `company_subscription_details` has one row per day/category, including shares bid, shares offered, and subscription multiple. The API joins these to the company and provides daily history. A changed intraday observation updates that day's summary; a new day retains a separate summary even if the multiple is unchanged. Earlier intraday source observations remain in the history table.

Percentages shown in the IPO table are subscription demand: `multiple × 100`, not category allocation quotas or allotment probabilities. Missing categories remain missing. NSE/BSE do not provide unofficial GMP; existing admin entry and separately configured unofficial feeds remain supported.

## Source implementation and honest readiness

- Built-in NSE current/upcoming IPO JSON parser, including total subscription when supplied. The current-issue response was inspectable during implementation; local direct requests timed out. Mirrored BSE issues without an authoritative BSE code/ISIN are rejected instead of inventing NSE identifiers.
- Built-in NSE UDiFF ZIP and BSE UDiFF CSV/ZIP parsers. A single bulk file per exchange is filtered against tracked identifiers. Unexpected schema, dates, invalid prices, archive limits, and HTTP denials fail explicitly.
- Native JSON discovery adapter for NSE/BSE IPO, category subscription, and financial discovery interfaces, configured with exact source field mappings rather than requiring a purchased normalized feed. It supports nested response paths, bounded pagination, date filters, and exact taxonomy concept mappings.
- Financial discovery downloads XML only for tracked companies and skips previously processed filing ID/timestamp pairs. New filing IDs or broadcast times cause a new download. A 14-day overlapping scan catches a missed Friday. Maximum five discovery pages and twenty XBRL downloads per run; hitting a limit is reported, never declared fully complete. Rerun after a filing batch limit. An outage beyond the lookback needs an explicit historical backfill.
- XBRL processing validates company ISIN, discrete fiscal quarters/full annual years, INR units, and reporting basis. Both consolidated and standalone can be retained; the existing UI prefers consolidated. Segment/YTD, ambiguous, unsafe XML, unsupported ratios, and unmapped taxonomy facts are rejected. Inline XBRL HTML is not supported by this parser; configure an actual XML instance download.

**Not yet live-validated:** BSE IPO/category discovery mappings and current NSE/BSE integrated-financial taxonomy mappings. Exchange requests were timing out (NSE) or returning access-denied responses (BSE) from this machine. No successful exchange import should be inferred from passing fixture tests. Do not enable a guessed mapping. Admin explicitly shows quarterly source mapping as incomplete until configured.

## Docker configuration

Preserve the existing `.env`; add or update only the intended settings:

```dotenv
EXCHANGE_DIRECT_ENABLED=true
MARKET_SCHEDULER_ENABLED=true
MARKET_SCHEDULER_DRIVER=celery
EXCHANGE_SOURCES_JSON=[]
TRADING_CALENDAR_YEAR=2026
TRADING_HOLIDAYS=<confirmed comma-separated exchange holiday dates>
```

The calendar must be populated and reviewed; do not copy the placeholder above. Missing or outdated calendar configuration blocks price collection. `EXCHANGE_SOURCES_JSON=[]` enables only built-in IPO/bhavcopy sources, not financial discovery. It does not need an API key. The existing `MARKET_FEEDS_JSON` remains available for optional approved feeds and unofficial GMP.

```powershell
cd C:\Coding\meraipo
docker compose up --build -d
docker compose ps
```

Open `http://localhost:3000/meraadmin`, sign in, and select **Data & scheduler**. Run a collection job, inspect its saved/error counts, then run the corresponding publishing job. Running publication with no valid staged records is explicitly skipped. Successful network retrieval with zero matching records is different from records published to the site.

## Native discovery mapping contract

Each `EXCHANGE_SOURCES_JSON` entry has:

- `name`, `exchange` (`NSE`/`BSE`), `kind` (`ipos`/`subscriptions`/`results`), and an official HTTPS `url`.
- `records_path`: dot-separated JSON path to the native array, or empty for a top-level array.
- `fields`: normalized target field to exact native field path. Nested targets such as `issue.name` are supported.
- `defaults`: explicit fixed metadata where the source requires it; never use this to fabricate prices, dates or results.
- `params`: request parameters; `{from}` and `{to}` expand to `DD-MM-YYYY`.
- Optional `page_param`, `size_param` (default `size`), and `page_size` (default 100).
- For results, `concepts`: metric names mapped to exact expanded XML QNames (`{namespace}Concept`). Review separately for each financial taxonomy/company type.

Result discovery must map at least an exchange identifier, `xbrl_url`, and `source_timestamp`; optionally map `filing_id` (otherwise the XML URL hash is used). Exchange-local naive timestamps are interpreted as IST. Source names/paths must be confirmed from actual official responses; examples in automated tests are deliberately fictional and are not deployment configuration.

Public sources reviewed:

- [NSE reports and UDiFF transition](https://www.nseindia.com/all-reports)
- [NSE current IPO response](https://www.nseindia.com/api/ipo-current-issue)
- [NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results)
- [NSE taxonomy downloads](https://www.nseindia.com/static/companies-listing/xbrl-information)
- [BSE bhavcopy](https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx)

Public access and public redistribution permission are separate, as explained in the supplied brief; this implementation does not grant exchange display rights.

## Verification

`tests/test_exchange_pipeline.py` covers ZIP/CSV parsing, identifier filtering, wrong dates, access denials without bypass attempts, collection/publication separation, repeat runs, NSE preference/BSE fallback, both-exchange history, relational daily subscriptions, ratio validation, Friday scheduling, financial XML parsing and publication, rejected-record recovery, and preventing duplicate scheduler ownership. Migration tests upgrade existing data, check model/schema agreement, and exercise downgrade/upgrade on a disposable database.

Browser tests exercise the popup on desktop and mobile, percentages, daily history, Escape/focus restoration, retry after failed requests, navigation to the company journey, admin controls, and existing critical flows. Fictional fixtures stay isolated from the running Docker database.

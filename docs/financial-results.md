# Financial results and IPO Tracker

## Deployment

The app uses the existing PostgreSQL, FastAPI, Celery and Next.js services.
Original attachments are immutable checksum-addressed rows in PostgreSQL (`result_attachments`), covered by the persistent database volume and database backups. They do not expire with seven-day bhavcopies.

```powershell
docker compose build api worker scheduler migrate web
docker compose run --rm migrate
docker compose up -d api worker scheduler web gateway
docker compose exec -T api python -m apps.worker.market_cli sync-results
```

Current migration head: `20261005_result_retry`. A pre-change database backup is in ignored `work/meraipo-before-results.dump`.

## Sources verified on 5 October 2026

NSE's public page script `/dist/js/sections/corporate-filings.js?v=01102026` identifies `/api/integrated-filing-results`, `type=Integrated Filing- Financials`, `page`, `size`, `symbol`, `from_date`, `to_date`, and `index=sme` for SME. Responses use `data` and `totalCount`. Both boards and every page are read, with repeated/inconsistent pages rejected. Only tracked exchange identifiers lead to attachment downloads.

Real original downloads retained as fixtures:

- PRANAV, consolidated quarter ended 30 June 2026, filed 1 October 2026: revenue INR 1,645,400,000, PAT INR 143,760,000, EPS INR 1.65. `tests/fixtures/nse-results-pranav-20261001.xml`.
- MANAV, standalone half-year ended 30 September 2025, revised 23 September 2026: revenue INR 94,288,000, PAT INR 4,132,000, EPS INR 0.31. `tests/fixtures/nse-results-manav-halfyear.xml`.

These verify two observed SEBI 2026-01-31 entry points: IntegratedFinance_IndAS and IntegratedFinance_OtherThanBank. They are public source fixtures, not invented production company rows. Publication to isolated test databases and the Company Details/Tracker read paths is covered by tests.

BSE landing page returns 200. Both supplied `NSTodayResults_Download/w` and page-verified `Corp_FinanceResult_ng_new/w` returned **403 SOURCE_ACCESS_BLOCKED** from the application environment. A cookie session did not resolve this. No challenge bypass, fabricated quarter ID or invented attachment was used.

BSE's own `chunk-DDBBOAZZ.js` / `chunk-SCEKLEXO.js` identify company history parameters `SCRIP_CD`, `FlagDur=7` (the page's company-selected history), `HFQ`, `ISUBGROUP_CODE`, `segment=C`; metadata fields `XMLName`, `Consol_XMLName`, `Resultpageurl`. The returned filenames are resolved under `/XBRLFILES/`. Response parsing is fixture-tested, but **live BSE history/download/publication remains unverified because access is blocked**. Historical metadata without a verified filing timestamp remains in review. The supplied MQ/MC CSV rows remain separate and are never interpreted as quarter IDs.

## Operation

Data & scheduler contains Financial results importer. Daily discovery defaults to **19:30 IST, including weekends**, configurable per exchange. The existing Celery beat checks saved times once per minute. Daily NSE discovery includes a rolling 14-day window. Sunday 20:30 IST queues sequential four-year histories for tracked listed companies, targeting at least eight quarters/four half-years and four annual periods where the source provides them. History completeness is recorded per company/exchange only after successful discovery. No synthetic missing periods are created.

Initial or manual history for one company:

```powershell
docker compose exec -T api python -m apps.worker.market_cli sync-results --company-id COMPANY_ID --from-date 2022-10-05 --to-date 2026-10-05 --confirm-backfill
```

Source failures are isolated; prior data remains. The shared market writer lease prevents overlapping publication. Attachments retry independently, with persistent Retry-After deadlines. A denied BSE source is not repeatedly queried for each company in one reconciliation batch; the daily/manual scan can test restored access.

Existing explicitly configured legacy financial feeds retain their collect/publish path. Built-in discovery is used when there is no explicit results feed. Vercel cron retains a fixed 19:30 IST default; configurable schedules and weekly histories use the deployed Celery scheduler.

## Review and storage rules

Manual BSE CSV can be previewed before saving discovery. Register a source filing with the exact exchange identifier, source URL, accounting basis and timezone-qualified filing timestamp; upload an original; review parsed values; publish the unchanged checksum preview. Existing admin session and CSRF protections apply. Unresolved identifiers can be mapped explicitly by an admin; filing identity is still cross-checked during parsing.

Manual HTTP uploads have the app's existing 1 MB request limit. Automated downloads allow up to 10 MB. Valid PDF/Excel/inline XBRL originals remain downloadable but require parsing review; no OCR or spreadsheet guesses are published. Unknown versions, sector templates, ambiguous contexts, conflicting values and units remain in review. Do not describe these as successfully parsed financial results.

Amounts use Decimal and are stored as exact INR decimal strings. XBRL `decimals` and `LevelOfRounding` do not multiply facts already denominated in INR. EPS stays INR/share. Current and comparative periods are not silently mixed; nine-month and half-year durations never become quarters. Segment contexts are excluded. Canonical identity includes company, start/end dates, duration type and basis; old versions remain. Equivalent exchange filings add provenance, never totals; conflicts require review.

Revenue, total income, PBT, total PAT, owner-attributed PAT where supported, basic and diluted EPS are retained. Debt, OPM, ROCE and cash-flow calculations are not fabricated; this release's reviewed mappings do not publish those optional metrics. Unsupported older taxonomies require a reviewed mapping before publication.

## Tracker diagnosis and fixes

Verified live before enabling display:

- 20 daily-close observations, 18 company snapshots, zero legacy quarterly rows and zero new canonical result rows.
- Both exchange `public_display_allowed` flags were false, so all public CMPs were hidden.
- The tracker defaulted to the current quarter, excluding September listings after the October boundary.
- The tracker originally read only legacy quarterly rows, so new canonical results would not reach it.

Fixed: the user explicitly confirmed display rights for both exchanges; both flags were enabled and cache invalidated. The tracker API then returned **18 populated CMPs**. Default listing-date filters now show all dates. The tracker reads canonical validated quarterly results in the existing crore contract, keeps one accounting basis and excludes half-years from quarterly growth screens. Company Details exposes separate duration/basis selectors.

The initial live NSE 14-day scan returned 61 filings, none matching tracked identifiers. Four-year company histories for all 14 tracked listed NSE identifiers completed with zero matching filings. A PRANAV control query using the same four-year window returned filings, ruling out a broken date filter. These are successful empty discoveries for those tracked identifiers, not fabricated financial data. BSE access is still blocked. The remedies are permitted BSE access or official-file upload, and additional reviewed source coverage where filings are not published through NSE integrated filing. Future daily scans can populate newly published results.

Missing future/first closes stay blank. Five companies had no usable historical BSE close after listing on 30 September/1 October; six more companies reached their scheduled listing date on 5 October. No issue price is substituted for a market close.

## Validation

Full backend baseline: 205 tests passed. Follow-up tests cover the final Tracker read path, real SME half-year fixture, pagination, revisions, BSE fixture/manual publication, admin preview, authentication, cookies/redirects and source isolation. Frontend unit tests cover Issue size ordering/null/zero/units, financial selectors and growth. Desktop/mobile browser assertions cover Issue size and scheduler; the Windows Playwright harness requires interruption after completed assertions because child-server teardown hangs. Production builds, migration and API health are checked separately.

Final verification: 45 API/importer/migration regression tests passed; the final importer subset passed 21 tests. Production browser verification returned HTTP 200, 29 listed companies, 18 visible closing prices, 25 rendered first-page rows and no desktop/mobile page overflow. Captures: `work/ipo-tracker-live.png` and `work/ipo-tracker-mobile.png`. The final 1 October BSE price retry remained `NOT_YET_PUBLISHED`; NSE re-import reported 13 unchanged rows. Fourteen successful company-history checkpoints are stored.

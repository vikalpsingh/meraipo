# Daily closing price sync

The existing `sync-prices` Celery job now downloads final cash-equity UDiFF files at
**19:00 Asia/Kolkata**, retrying at **20:00 and 22:00**. It cleans original files older
than seven days **before** checking calendars/downloading. It does not delete historical
prices, revisions, checksums, or job metadata. A persistent `bhavcopies` Docker volume is
shared by API and worker. Keep one Celery beat instance; Vercel cron is an alternative
driver, never a second scheduler. The existing global database writer lease excludes
concurrent market imports. Each backfill date uses a separate bounded execution.

## Verified sources and remaining setup

On 4 October 2026 the running API container successfully downloaded the NSE file for
1 October 2026 from:

`https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261001_F_0000.csv.zip`

The official [NSE reports page](https://www.nseindia.com/all-reports) identifies this
as “CM-UDiFF Common Bhavcopy Final (zip)”. The real sample retained in
`tests/fixtures/nse-udiff-20261001-sample.csv` contains only the fields needed to test
the mapping. `20MICRONS` has `ClsPric=207.26`, while `LastPric=205.35`; close uses
`ClsPric`. Observed `Src=NSE`, `Sgmt=CM`, `FinInstrmTp=STK`, `SsnId=F1`.

The user-supplied BSE route was verified against **29 September 2026**:

`https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20260929_F_0000.CSV`

The original CSV contains 5,046 rows; the strict parser accepted all 5,046 with no
validation errors. Observed `Src=BSE`, `Sgmt=CM`, `FinInstrmTp=STK`, `SsnId=F1`;
BSE series are groups such as `A`, rather than NSE's `EQ`. The retained BSE sample
has `ARE&M` closing at `766.35` versus last trade `764.50`. Both exchange samples
are tested through HTTP, importer, numeric database, summary and chart retrieval.
Corrections used in automated tests are synthetic modifications of those samples.

On the same verification run BSE returned **404 for 1 October** and **406 for
30 September**. Date-specific failures remain visible and never cause a silent
fallback to a different date. A configured route is not a guarantee of daily availability.
Manual original-file upload remains available. The BSE reports page itself returned
406, but direct download of the supplied route for 29 September succeeded. A later
request for 29 September returned 404; its retained original was imported successfully
through the same upload/parser service, rather than retrying around access restrictions.

The example calendars were independently checked against
[NSE/CMTR/71775](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf) and
[BSE notice 20251212-8](https://www.bseindia.com/markets/MarketInfo/DispNewNoticesCirculars.aspx?page=20251212-8).
Both include the announced 8 November 2026 Muhurat session. Review later exchange
circulars for amendments and special-session timing. Configure each exchange/year
explicitly; a missing calendar fails closed. A 404 is never treated as a holiday.
No previous-day substitution occurs: on a holiday the dated scheduled run is skipped;
use the selected completed date for a manual import.

## Configuration and operation

Use **MeraAdmin → Data & scheduler → NSE / BSE daily closing files** to enable exchanges,
set verified URL templates/calendars, preview uploads, import them, run a selected date,
backfill up to 31 dates, and download errors. Upload preview writes no price records.
Admin actions retain session/CSRF protections. The normal Config tab preserves these
exchange settings. `BHAVCOPY_SOURCES_JSON` is the environment fallback; saved admin
configuration takes precedence.

Public display defaults to **disabled per exchange** until data-use rights are established.
Ingestion and authenticated preview work while public prices/charts remain hidden.
Enable public display only with permission to redistribute the exchange data. The private
endpoint is `GET /api/v1/admin/bhavcopy/prices/{company_id}?exchange=NSE`.

Commands from the repository root (Docker must be running):

```sh
docker compose build api worker scheduler migrate web
docker compose run --rm migrate
docker compose up -d api worker scheduler web gateway
docker compose cp docs/bhavcopy-sources.example.json api:/app/work/bhavcopy-sources.json
docker compose exec api python -m apps.worker.bhavcopy_cli configure --file /app/work/bhavcopy-sources.json
docker compose exec api python -m apps.worker.bhavcopy_cli sync --date 2026-10-01
docker compose exec api python -m apps.worker.bhavcopy_cli status
docker compose logs --tail=100 worker scheduler
```

Configuration preserves global scheduler enablement. Enable **scheduled jobs** in Config
after setup, keeping `MARKET_SCHEDULER_DRIVER=celery` for Docker. The CLI runs the same
durable job synchronously under the same database lease; the admin queues it to Celery.

```sh
docker compose exec api python -m apps.worker.bhavcopy_cli backfill --from-date 2026-09-28 --to-date 2026-10-01 --exchange NSE
docker compose cp /path/to/original.zip api:/app/work/original.zip
docker compose exec api python -m apps.worker.bhavcopy_cli upload --exchange BSE --date 2026-10-01 --file /app/work/original.zip
docker compose exec api python -m apps.worker.bhavcopy_cli upload --exchange BSE --date 2026-10-01 --file /app/work/original.zip --apply
```

Omit `--apply` for preview. Use `python -m alembic upgrade head` for non-Docker migrations.
Never run test suites against the application database; tests use isolated databases.

## Data design

Each file is parsed once per import. A dictionary of tracked listed companies matches
ISIN and verified NSE ticker/BSE security code or BSE symbol, rejecting conflicting identifiers and
duplicate series/session rows. Names and BSE issue IDs are not security keys. No identifier
is inferred from a company name. Missing or invalid prices never overwrite a valid close.

`equity_daily_closes` stores Decimal-backed numeric OHLC, previous close and volume,
security identifiers, and the source-file foreign key. The unique indexed key
`(company_id, exchange, trade_date)` provides direct date lookup; page reads never scan
download files. Identical imports leave prices unchanged. Corrected values retain the
previous values and source file in `equity_close_revisions`, even after the original file
expires. `bhavcopy_files` retains source, date, SHA-256, retrieval/import times, counts,
errors and cleanup time.

The first successfully imported exchange becomes a company's fixed chart exchange
(NSE is processed first in a both-exchange run). Other exchange prices remain available
in private history without alternating the default chart. `company_price_snapshots`
is rebuilt from that exchange's latest record; an older backfill cannot replace its
latest date. ATH/52-week values describe **imported history coverage**, not a claim of
complete exchange history. Quotes are raw, unadjusted for corporate actions. Existing
legacy/intraday records stay separate. Daily change is null without a positive previous
close. IPO Tracker shows the closing date and source exchange when display is permitted.

HTTP requests use finite timeouts, maximum three attempts and size limits. ZIP handling
never extracts paths and rejects traversal, multiple members, encryption and oversized
content. Access denials stop immediately; the same day's scheduled retries require admin
attention after a denial. Retry-After deadlines persist across runs, including scheduled retries. Unsupported
headers/encoding/session IDs fail visibly instead of being guessed.

Tests: `python -m pytest tests/test_bhavcopy.py -q`; the broader regression suite remains
`python -m pytest -q`. Source verification requires actual exchange access, not fixtures.


## Live verification on 4 October 2026

- Database migration: `20261004_bhavcopy_retry`; app, worker and scheduler rebuilt/restarted.
- NSE 1 October: 3,712 source rows, 13 tracked matches, 13 inserted closes, zero rejected.
- BSE 29 September: 5,046 source rows, 7 tracked matches, 7 inserted closes, zero rejected.
- Coverage: 20 exchange/date records for 18 of 23 non-demo listed companies.
- Repeating both files: zero inserted/updated records; 13 NSE and 7 BSE unchanged.
- Independent CSV/SHA-256 checks confirmed all 20 stored closes and all 18 latest summaries.
- A real Celery worker run (`0c8cf1e3-e641-4acb-8c31-95879ae664f0`) completed successfully.
- Global scheduling is enabled with the Celery driver; closing sync is not paused.
- Public-display permissions remain disabled; authenticated private history is available in Data & scheduler.
- Five companies await newer BSE rows: S. K. Offset, Unitec Fibres and Liqvd Digital
  (listing date 30 September); Roopa Screen and Peshwa Wheat (listing date 1 October).
  The successful 29 September file predates those listings. Do not fabricate prices or
  assign another security's close to fill these gaps.

A pre-migration database backup is retained locally in the ignored
`work/meraipo-before-bhavcopy.dump`. Job history retains failed attempts as well as
successful imports; this is intentional audit history.

Validation: all **190 backend tests passed**. TypeScript, ESLint, Ruff, shared-package
MyPy, formatting checks and the production Docker builds passed. Desktop/mobile
scheduler browser assertions passed; the Windows browser harness stalled during teardown
and was stopped after completion. A separate final mobile layout check passed with no
horizontal overflow. Backend readiness and Tracker returned HTTP 200; unauthenticated
bhavcopy admin access returned HTTP 401.

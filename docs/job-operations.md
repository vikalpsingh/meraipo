# MeraAdmin job operations

`Data & scheduler` opens on five operational cards: IPO sync plus independent
NSE/BSE closing-price and quarterly-results jobs. Source uploads, mapping review,
provider configuration and legacy tools have separate views.

## Scheduling

The Celery scheduler polls once per minute in Asia/Kolkata. Exchange identities are
`sync-prices-nse`, `sync-prices-bse`, `sync-results-nse`, `sync-results-bse`.
Price schedules support 1–6 daily HH:MM attempts per exchange. Results retain one
daily discovery time per exchange, shared with the existing Results source form.
Defaults remain 19:00/20:00/22:00 for prices and 19:30 for results. Existing source
enablement, global enablement and inherited parent pauses are preserved.

Each due slot has a unique database key (job + IST minute), so duplicate scheduler
notifications cannot create duplicate runs. Jobs due together are dispatched as a
sequential chain because publication uses a shared database writer lock. Weekly
results backfills also use separate exchange identities and respect source/pause
settings. Older combined jobs remain readable in history and callable for legacy
clients; Celery no longer schedules those combined price/results jobs.

Configure `market_scheduler_driver=celery` to use these editable times. External
Vercel cron timing is managed outside this UI and is explicitly labelled as such.
A job that encounters an already-held writer lock records SKIPPED with the reason;
a manual retry can run after the competing import completes.

## Investigation flow

1. Inspect latest attempt, last successful run, next run, duration and record counts.
   Last success is queried independently of the latest 50 runs. A successful filing
   scan with zero matches is distinguished from an import failure.
2. Open **View runs & logs**. Filter by job and status; history is paginated.
3. Inspect the run ID, timestamps, trigger, parameters, counters and its own errors.
   Error details include source/record identifiers and next steps. Price files include
   trading date, safe source URL, checksum, retry-after, row-error samples and CSV download.
4. Correct source access/configuration or company mappings in the recovery views.
   Retry a single exchange/date or bounded results range. Previously published data
   remains available while a source is unavailable.

Endpoints require the existing administrator session; writes also require CSRF and
same-origin checks. Schedule changes and source-setting writes create audit records.
Diagnostics do not expose configured secrets or raw upstream response bodies.
RUNNING attempts older than 10 minutes and QUEUED attempts older than 60 minutes are
marked WORKER_TIMEOUT when the overview refreshes; this is crash visibility, not a
worker heartbeat. Use the run ID to correlate worker logs before retrying.

## Deployment and checks

Apply `20261005_job_schedules`, then restart API, worker, scheduler and web together.
Tests cover exchange parameter isolation, atomic slot claims, duplicate ticks,
parent-pause inheritance, disabled sources, calendar/timezone timing, validation,
authentication/CSRF, queue failures, filtered diagnostics and source-specific failures.
Frontend tests cover each card's request target, schedule saves and log navigation.

# MeraAdmin scheduling and diagnostics

The five primary jobs are configurable in **Data & scheduler → Jobs & schedules →
Schedule & configuration**. Every job supports hourly, daily and weekly execution.
All timing uses Asia/Kolkata (IST).

The requested default daily sequence is:

| Job | IST |
| --- | --- |
| NSE closing prices | 19:00 |
| BSE closing prices | 20:00 |
| NSE quarterly results | 21:00 |
| BSE quarterly results | 22:00 |
| IPO, subscription and GMP sync | 23:00 |

Hourly schedules choose a minute past every hour. Daily schedules choose HH:MM;
price jobs may have additional explicit retry times. Weekly schedules choose a
weekday and HH:MM. Next-run labels use the same calculation as the scheduler.
Existing global/source enablement and paused preferences remain respected.
The weekly results-history maintenance chain runs Monday at 00:00, one hour after
the Sunday IPO sync, and uses the same queued exchange jobs.

## Queue and failure behavior

Celery checks schedules every minute. A unique (job, IST minute) database key
prevents duplicate scheduled runs. Due jobs are published as a sequential chain.
The five primary job identities also enforce FIFO across independently queued
manual runs and maintenance chains. The shared database writer lease prevents
concurrent publication. If a predecessor or another writer is active, the run
remains QUEUED with WAITING_FOR_PREVIOUS_JOB; Celery retries after 15 seconds without
holding a worker process. It automatically starts when its turn arrives. A failed
predecessor is terminal and does not block later jobs.

Waiting jobs do not expire merely because the queue is long. A queued run can be
cancelled from its diagnostics; an atomic QUEUED-to-RUNNING transition prevents a
cancelled run being executed. Worker attempts stuck RUNNING for over 10 minutes
are marked WORKER_TIMEOUT by the scheduler or overview. A broker delivery failure
is recorded as FAILED. If a queued run was orphaned by a process crash before
broker delivery, inspect worker health, cancel that queued run, and run it again.

## Operator flow

Cards show last attempt, last successful run, next run, duration and record counts.
Last success is queried independently of the latest 50 runs. A filing scan with no
new matching records is explicitly distinguished from an import failure.

Open **View runs & logs** to filter paginated history and inspect the run ID,
trigger, timestamps, parameters, counters and its own errors. Diagnostics identify
the source/record and recovery steps. Closing files include the safe source URL,
trading date, checksum, retry-after and a rejected-row CSV download.

Source access, calendars, uploads and results review are in separate recovery
views. Fix a source or identifier mapping, then retry just that exchange/date.
Previously published data remains available during source failures. Historical
combined-job runs are still readable; Celery no longer schedules combined jobs.

Authentication and CSRF protect these endpoints. Schedule/source/cancel operations
are audited. Diagnostics do not expose provider secrets or raw upstream bodies.
Editable timing requires the Celery driver; external Vercel cron timing is managed
separately and explicitly labelled in the UI.

## Validation and deployment

Apply migrations through `20261005_job_frequency`; restart API, worker, scheduler
and web. Tests cover NSE/BSE isolation, duplicate schedule ticks, inherited pauses,
disabled sources, hourly/daily/weekly rollover, permissions, FIFO waits and release,
queue failures, cancellation, date imports and filtered run diagnostics. Frontend
tests cover job request targets, frequency controls and selected-run errors.

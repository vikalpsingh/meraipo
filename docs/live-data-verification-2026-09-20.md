# Live data verification attempt — 20 September 2026

Checked the local checkout at approximately 10:09 IST. No secrets were printed or changed.

| Check | Observed result |
|---|---|
| Local `.env` | Absent |
| Configured market feeds | None |
| Automatic scheduling | Disabled |
| Cron authentication secret | Not configured |
| Trading calendar year | Not configured (0) |
| PostgreSQL, localhost:5432 | Not listening |
| Redis, localhost:6379 | Not listening |
| FastAPI, localhost:8000 | Not listening |
| Web app, localhost:3000 | Not listening |
| Docker engine | Unavailable; docker_engine named pipe missing |
| IPO-master manual dispatch through the shared scheduler code | NOT_QUEUED — ConnectionRefusedError |
| Other market jobs | Not invoked after confirming the shared database was unavailable |
| External provider requests | None |
| Live records imported in this attempt | None |
| Population of the deployed public site | Not verified; deployed API/site configuration has not been supplied |

The passing fixture tests do not establish live provider connectivity. This attempt does not claim that the deployed website has been refreshed.

To complete verification, provide the intended deployed site/API URL and approved provider documentation, configure endpoints/credentials privately on the API and worker, start PostgreSQL/Redis/API/Celery, apply migrations, and configure the confirmed exchange calendar. Then enqueue IPO master, active-issue subscription/GMP, EOD, results and reconciliation as applicable; inspect persisted run outcomes, source timestamps, saved records and their public API/UI values. Compare imported observations against the actual provider responses.

The application currently supports scheduled IPO/financial snapshots and end-of-day stock prices. It does not implement a streaming real-time tick feed. EOD jobs skip weekends according to the current scheduler policy; 20 September 2026 is a Sunday, so an EOD run would not be expected to fetch a new regular-session close.

See [integration setup](market-data.md) for environment, feed contracts, schedules and deployment steps.

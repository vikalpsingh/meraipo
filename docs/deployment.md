# Deployment

For Vercel hosting of the web application and the market-data cron configuration, follow [Market data deployment](market-data.md#j-deployment-sequence). FastAPI, PostgreSQL, Redis and the Celery worker continue on a separate backend host. Vercel cron only enqueues work.

Use container-capable AWS, Azure or an equivalent host, managed PostgreSQL, Redis, an object store and a TLS/CDN ingress. In the Compose deployment, route public traffic to the `gateway` service on port 3000. It proxies Next.js and returns the standalone `maintenance.html` with HTTP 503 when the web service is rebuilding, restarting or unavailable. Keep the gateway running while replacing the web container. API/web are stateless and workers run separately. Do not use the prototype Sites Worker deployment for this stack.

Local: copy .env.example to .env, run docker compose up --build. Migrations run in a one-shot service before API/worker. Demo seed is opt-in and prohibited in production. Create the admin via the password-prompt CLI; never pass passwords on the command line. During later releases, build images first and recreate `web` without recreating `gateway`; the gateway continues serving the maintenance response while Next.js is unavailable.

Release: run the full verification script/CI including PostgreSQL/Redis integration and Playwright; build immutable images; back up DB; apply migrations once; deploy to staging; run smoke tests; promote that exact image digest. Never deploy when a required check is skipped or failing. Restrict GitHub production environments and branch protection externally.

Backups: managed PostgreSQL daily snapshots and PITR, S3 versioning and retention, encrypted secrets backup with restricted access. Restore into a new database, replay WAL to a chosen timestamp, restore object versions, run integrity/route checks, then switch connections. Perform periodic restore drills. Roll back application images; avoid destructive down-migrations of historical data.

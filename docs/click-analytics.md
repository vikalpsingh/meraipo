# Lightweight click analytics

MeraAdmin > Analytics shows today, calendar week (Monday onward), and calendar month totals in Asia/Kolkata, plus daily (30 days), weekly (12 weeks), and monthly (13 months) breakdowns. Current periods are partial. Counts begin on deployment; historical traffic is unavailable.

The first-party client records trusted link/button activations (including keyboard-generated clicks), grouped by the source page section. It excludes /meraadmin, admin links, disabled controls and Do Not Track browsers. It batches every 15 seconds, on route changes, page hide, or 100 pending clicks. No page views, unique visitors, click text, full URLs or individual events are stored. Telemetry is best effort without retry; bots and dropped requests can affect totals. Dates are assigned on server receipt.

POST /api/v1/analytics/clicks accepts a strict count of 1–100 and one of seven fixed sections. Origin validation and a single expiring Redis global rate counter (3,000 batches/minute) bound ingestion. Redis failure drops telemetry with 503, without affecting browsing. Counters use an atomic PostgreSQL upsert; SQLite is supported for tests. One row per section per IST day means at most 2,800 rows across a rolling 400-day window. Expired rows are pruned on writes and authenticated report reads. No new service or scheduled job is needed.

GET /api/v1/admin/analytics requires the existing admin session and returns no-store responses. Analytics adds no identity storage; ordinary server security/access logs are separate.

Deploy the migration before the updated API, then rebuild web. Local Compose: docker compose up -d --build api web. Existing worker/scheduler behavior is unchanged.

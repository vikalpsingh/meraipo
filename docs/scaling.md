# Scaling

Start with one web/API deployment, PostgreSQL, Redis and one worker. CDN serves static assets. API cache uses bounded TTLs and a shared generation key invalidated after writes. Connections use bounded pools. Lists paginate and joined/select-in loading avoids per-row queries. Measure p95 API latency, DB duration, cache hits, errors, job failures and freshness before changing capacity.

At higher load add web/API replicas and worker concurrency, upgrade PostgreSQL, and add read replicas only after measured need. Sessions and rate limits are shared; no sticky sessions. Redis coordination and stable job keys permit worker replicas. No sharding or microservices are required for V1.

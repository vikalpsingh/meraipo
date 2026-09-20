# Providers

Replaceable IPO, results, market price, GMP and document protocols live in packages/providers. Manual and demo adapters work without credentials. Live adapters remain disabled until documented access and public display rights are confirmed. Do not scrape Screener: store outbound research links only.

Worker flow: fetch -> validate -> source provenance -> transactional upsert -> calculate -> cache generation bump. Stable import keys make repeated deliveries idempotent. Conflicts create quality issues and never silently replace verified data. Retried tasks use exponential backoff; exhausted runs are recorded for admin review.

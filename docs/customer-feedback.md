# Customer feedback

The homepage links to `/feedback`. It shows the five approved feature requests with the most votes, a published/delivered summary, and a form for feature ideas or private general feedback. Equal vote counts sort by submission time and ID. There are no seeded customer requests or fabricated votes.

`customer_feedback` stores the original title, body, type, review status, hashed browser identity and submission idempotency key. `customer_feedback_votes` stores one row per request/browser, enforced by a database uniqueness constraint. Vote totals are calculated from those rows, not client-supplied counts. Repeated submissions with the same browser/key and repeated vote requests do not duplicate data. Visitors can undo votes.

The browser uses a random HttpOnly, SameSite cookie. Votes are per browser, not verified people: clearing cookies or using another device creates another browser identity. Public writes require the configured origin and are rate limited through Redis (five submissions/hour, sixty vote operations/minute per browser). Public personalized responses are never shared-cacheable. Redis failure blocks writes outside test mode. No email, name or account is required.

New submissions start `PENDING`. In `/meraadmin` → **Customer feedback**, the administrator can publish a feature for voting, mark it planned/in progress/delivered, or hide it. General feedback can only remain pending, be marked reviewed, or hidden; it is never published. Reviews use existing admin authentication/CSRF controls and create audit entries. The inbox is paginated in batches of 25. The public board exposes neither browser hashes nor submission keys.

Migration: `20260921_customer_feedback`. Existing database records are preserved. Start with `docker compose up -d --build`; the migrate service applies the schema before API startup.

Validation: `tests/test_feedback.py` covers storage, retries, unique/undo votes, ranking, moderation, private data, origin/cookie guards, authentication and rate limits. `apps/web/tests/e2e/feedback.spec.ts` exercises visitor submission → admin review → public voting on desktop/mobile and retries a failed submission without losing input.

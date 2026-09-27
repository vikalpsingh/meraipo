# IPO provider integration

IPO master discovery is selected with `IPO_DATA_PROVIDER=exchange|ipoalerts|feed`.
The default remains `exchange` for compatibility. `ipoalerts` uses the adapter registry in
`packages/providers/ipo.py`; future vendors implement the same `IPOBatch` contract and
normalize to `Issue`. UI and master schemas do not depend on vendor JSON field names.

## IPOAlerts setup

Set `IPO_DATA_PROVIDER=ipoalerts`, `IPOALERTS_API_KEY` and `IPOALERTS_PAGE_SIZE=3` on the
backend. Never use a NEXT_PUBLIC variable for the key. The key is a redacted SecretStr,
transmitted only in the x-api-key header to https://api.ipoalerts.in. Redirects are rejected.
Docker passes these settings only to API, migration, worker and scheduler services.
The tested account permits three IPOs per page; raise the page size only when the plan permits.
Requests are spaced by 10.1 seconds for the six-request/minute tier. HTTP 429 stops collection
with an actionable job error instead of repeatedly exhausting the quota.

The daily `sync-ipos` job remains at **23:00 Asia/Kolkata**. The three configured discovery
statuses are open, upcoming and announced, including both EQ and SME. No exchange filter is
sent. Announced records lacking a security type remain Unknown; dates are never fabricated.
The historical closed/listed catalogues are not fetched by this daily discovery job. Existing
masters continue through the existing date-driven lifecycle reconciliation. Historical backfill
and post-listing prices/results remain separate jobs. IPOAlerts source data is aggregated
provider content, not an independent editorial verification or direct NSE/BSE response.

## Publication and identity

1. Validate complete pagination metadata for each status. Restricted preview responses,
   repeated IDs, changing page totals and incomplete status batches are rejected.
2. Preserve complete raw pages, normalize records, and stage valid rows. Invalid rows get
   provider ID errors in MeraAdmin. No records are deleted because they disappeared from a feed.
3. Commit staging durably, then publish masters within the same job and shared writer lease.
4. Preserve existing public slugs, identifiers, subscriptions and price/result history. The
   selected provider can replace earlier machine-sourced IPO values, with normal audit history.
5. Invalidate the public cache after publication. A repeat with identical values is idempotent.

The stable vendor ID uses its own IPOALERTS identifier namespace. The public ticker projection
excludes provider IDs. NSE symbols can be obtained from the provider's matching official NSE
URL; BSE IPONo is an issue ID, never a six-digit stock code. A legacy NSE BSE_SYMBOL mirror can
be bridged only when the exact symbol, issuer name, board and both bidding dates agree. Conflicting
identities are rejected. There is no fuzzy name-based merge.

`ipo_provider_details` holds full descriptions, all strengths/risks, the complete date-only
schedule, reported minimum amount, provider links, retrieval time and raw-page reference.
It is linked to the IPO master and is exposed via `provider_details`. Editorial guides take
precedence; vendor content is labelled as not independently reviewed. Date-only mandate events
do not become invented timed deadlines. Reported minimum amount is distinct from a verified
application calculator rule, especially for SME issues.

## Independent datasets

The base IPO response has no subscription category data. With direct exchange access enabled,
`NSE_SUBSCRIPTION_CATEGORIES_ENABLED=true` collects the official `ipo-active-category` endpoint
for exact NSE identifiers, including newly staged IPOs and the three days after closing.
The consolidated snapshot is used as a whole; exchange-only totals are never added to it.
The parser retains NSE's updateTime in IST, validates ratios against bid/offered shares, and
leaves zero-allocation categories unavailable. Configured BSE/category feeds remain independent
of catalogue ownership. BSE-only issues without a verified NSE identifier need their BSE mapping.
Missing category-feed configuration is recorded as `SUBSCRIPTION_CATEGORIES_NOT_CONFIGURED`
in the job log. Totals cannot be used to infer Retail/QIB/NII allocations.

IPOAlerts requests include `includeGmp=true`. Where the account returns a quote, the adapter
stores its mean premium as an unofficial GMP observation with the provider's original timestamp.
Zero and negative premiums are valid; absent quotes remain missing. Invalid GMP does not discard
an otherwise valid IPO record. The raw page retains the individual quote sources/aggregations.

Daily price sync runs at 23:10 IST every day. Weekend and configured holiday requests resolve
backwards to the latest trading date within the configured calendar year (bounded to 15 days).
The run records requested/resolved dates; master rows retain the actual trading date. Repeating
the job does not create duplicate daily prices. Missing calendar coverage fails visibly instead
of guessing, and an exchange download failure does not discard the other exchange's valid file.
BSE official symbols can match existing BSE_SYMBOL mappings before a scrip code is known.

## Operational limits

Collection remains bounded by the existing 170-second budget and 20 pages per status. An
account whose catalogue exceeds this budget needs an appropriate provider plan/page size;
the job reports a partial result and never calls an incomplete status complete. Completed
status batches can still publish. Authentication, schema, rate, pagination and row errors are
shown at the bottom of MeraAdmin. A configured key indicator is not proof of valid access.

## Verification

`tests/test_ipoalerts.py` uses synthetic payloads and httpx MockTransport for authentication,
pagination, preview rejection, transport/rate failures, master population, duplicate prevention,
provider switching, public projection and safe admin logs. Migration tests upgrade an existing
schema, check model parity, downgrade, and upgrade again. Browser tests exercise the public
search, company popup and application guide on desktop and mobile. Live records are never used
as test fixtures in the production database.

API contract sources:
- https://ipoalerts.in/docs/api-reference/authentication
- https://ipoalerts.in/docs/api-reference/endpoints/get-all-ipos
- https://ipoalerts.in/docs/api-reference/ipo-object
- https://ipoalerts.in/docs/api-reference/pagination
- https://ipoalerts.in/docs/api-reference/rate-limits

## Live verification — 21 September 2026

Authenticated Celery run `0a61604f-56e5-4d5d-baaf-5981f124587c` completed SUCCESS:
36 fetched, 1 written, 35 unchanged, zero failed, 13 API pages. All 36 provider-detail
masters were populated. The previous run retained one rejected record's old master;
the repeat recovered it without duplicating the other 35. Public API counts were
8 OPEN, 11 scheduled UPCOMING and 17 ANNOUNCED (the API's upcoming category contains
both latter groups; the homepage separates them). A BSE-only company's homepage
popup and company journey were checked on desktop and mobile, with all ten provider
schedule entries and no browser runtime errors or horizontal overflow.

The configured key is not recorded in this document. This deployment was verified
on the local Docker site; a public HTTPS production deployment is a separate operation.

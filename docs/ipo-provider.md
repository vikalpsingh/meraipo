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

## IPOAlerts plan rejection investigation — 2026-10-15

Reported production run: `3cccf710-a946-455e-87ef-e5b93499cbdd`, 2026-10-14 23:00 IST.
The historical `IPOALERTS_HTTP_ERROR` discarded HTTP status/body, so the original
response cannot be reconstructed from that error alone. Local Docker was unable
to start; the production run/database and active production key were not verified.

Read-only requests using the locally configured key reproduced:
- `includeGmp=true`, limit 3: HTTP 400, `ERR:PRMFBNGMP` (GMP not enabled for plan).
- No GMP, limit 3: HTTP 400, `Limit must be less than or equal to 1`.
- No GMP, limit 1: HTTP 200; nine open IPOs, nine pages, one record returned.

The adapter now handles only these explicit restrictions with bounded, paced
retries. The allowed page size and GMP exclusion persist across subsequent pages
within the run. GMP unavailability remains a job error (partial status), while
complete IPO status batches can publish. Existing GMP quotes are retained.
Unknown HTTP rejections retain status and safe request context in job details;
headers, credentials, and arbitrary upstream error text are not persisted.

Provider contract: https://ipoalerts.in/docs/api-reference/endpoints/get-all-ipos
GMP requires the Pro plan and GMP add-on. Provider plan changes are external;
this patch cannot enable GMP entitlement. Existing pagination/time-budget guards
still apply, particularly for large catalogues on a one-record-per-page plan.

Deployment and production rerun require a working Docker engine and verification
of production configuration. A successful single live page is not evidence that
the full production catalogue was imported.

## IPOWEB provider (2026-10-16)

IPOWEB brings the trading app's NSE + IPOWatch discovery approach into MeraIPO;
it does not import MeraIPO's own website. It also reuses the existing BSE IPO
parser. MeraAdmin → Data and scheduler → Market data configuration provides a
single active IPO provider and individual NSE/BSE/IPOWatch source toggles.
Select IPOWEB and save; select IPOAlerts later to restore that provider without
removing its encrypted key or existing companies. IPOWEB is the default for new
configuration and the local environment. Existing saved database configuration
takes precedence and must be changed in MeraAdmin after deployment.

Official rows retain NSE/BSE provenance; IPOWatch rows are UNOFFICIAL and marked
unverified. Stable source IDs and exchange identifiers are used first. Across
providers, exact normalized issuer names require matching opening/closing dates
and compatible boards. Ambiguous or undated matches are rejected for review,
not inserted as another company. Source failures leave published rows intact.

The trading app guesses symbols from company words; this adapter deliberately
does not. Missing issue size, lot size and prices remain missing. The current
IPOWatch table does not include issue size/lot size, so these need an exchange
feed or subsequent enrichment. GMP is not published from this table because it
has no explicit quote observation timestamp; ingestion time is not quote time.

Verification: nine focused backend tests (including staging/public catalog,
repeat imports, provider switching and conflict rejection), two MeraAdmin UI
tests, TypeScript check. Full suite intentionally not run. A separate read-only
live IPOWatch probe respected robots policy and parsed 11 records with zero
rejected rows; it did not write the database. Docker was subsequently started and the local stack rebuilt/deployed. IPOWEB
was enabled in saved market configuration with an audit record; the existing
API key was preserved. A database backup is retained in ignored work/. Public
remote production deployment is not implied by this local verification.

Live sync run `7f5ce356-9066-491e-bac1-cbfec1f3a6ae` completed PARTIAL with
32 fetched, 25 written, 2 unchanged and 6 failures; conflicting records remain
held for review rather than overwriting existing published values.
Final database verification: 14 IPOs are attributed to IPOWEB; company count rose
from 74 to 79 (five new companies). BSE returned HTTP 403. Four IPOWatch rows
(Jio Platforms, Bonfiglioli Transmissions, Fusion CX, HD Fire Protect) conflicted
with stored values and were retained for review. Paras Healthcare required
identity review. These exceptions did not erase published company data.

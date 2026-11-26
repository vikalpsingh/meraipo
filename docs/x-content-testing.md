# Test market and current-IPO content in MeraAdmin

These controls generate drafts and can publish real public posts to @MeraIPO. No
schema migration is needed. Deploy API, worker, scheduler and web together with the
existing production Compose/environment options. Existing schedules remain unchanged.

## Daily market update · OpenAI

1. Confirm the OpenAI API key has billing/quota and the configured model supports
   Responses, web search and structured output. A stored key alone does not verify access.
2. Click **1. Generate today's market update · test** in the market schedule row.
   The schedule can remain disabled. One explicitly requested paid research test is
   allowed per IST day, separately from the one scheduled request. Repeated clicks
   load the existing test. Failed/uncertain calls are not automatically retried.
3. Review **Generated content test**: the exact public text, status and private source
   evidence. Sources are not appended to the public post. The provider receives the
   market prompt in `packages/providers/market_research.py`, with server IST time,
   configured exchange calendar, previous session and pre-market/intraday/closing phase.
4. `SKIP_POST` is stored as SKIPPED and cannot be approved/published. Weekend tests
   skip without calling OpenAI. Inadequate evidence skips with a saved explanation.
   Invalid source URLs, stale/future dates and malformed formats remain blocked.
5. Click **Approve test content**, then **Publish test content to X**. Wait for PUBLISHED
   and open the X link. Review source dates and all figures before approval.
6. After a successful approved market test or daily market post, save the daily time
   and enable the schedule, global automatic publishing, and the separate market
   automation option. Connection-test/manual posts do not qualify for this gate.

Public market text is one plain-text post with exactly #StockMarket, no links,
Markdown or citations, and a conservative 280-weighted-character bound. The model is
instructed to omit individual company names, avoid guarantees, use rounded levels,
label previous-session data and omit unverified metrics. Numeric claims are checked
against retrieved-source provenance/date metadata, not independently recalculated
from a licensed quote feed; review remains important. JSON exists only as the private
API evidence envelope; it is never sent as the X post.

Market schedules run on weekdays, including exchange holidays (closure + global/
commodity cues). After 15:30 IST they request closing summaries if closing data is
verified. IPO event schedules remain trading-day-only. Calendar coverage must be valid;
unknown years fail closed. The existing one-hour draft expiry still applies.

## IPO opening day · image included

1. Select a **Currently open IPO for test** in that schedule row.
2. Click **1. Generate selected IPO content and image · test**. No OpenAI call is made.
3. Review the text, saved public-feed provenance and **Review generated IPO image**.
   Test content says "open for subscription" and the image shows its actual opening
   date; it never claims an older IPO opens today. Freshness, cancellation, conflict,
   current bidding dates and public-source checks remain required.
4. Approve and publish using the same two controls. Tests always require approval,
   even with global automation enabled. Test ledgers do not consume the scheduled
   opening/closing event keys. Repeated requests return the same test for that IPO/day.
5. After verifying the published result, enable/save opening and closing schedules
   and the global automation toggle. Schedule IPO ingestion before those times.

All publishing retains account identity checks, spending/attempt caps and unknown-
outcome protection. Identical content across test and scheduled flows is blocked
with a reference to the existing post, rather than sent twice. A skipped result has
no unique content hash, so future skipped days do not conflict.

## Rollback

Disable the schedules and global auto-publishing first. Deploy the previous compatible
application images using existing deployment procedures. No credentials or schema
need changing. Keep the post ledger, especially PUBLISHED and UNCERTAIN records.

## Validation

Local tests mock OpenAI and X. Production billing, research retrieval, image upload
and actual public delivery require the administrator's live test flow above.
X character-count reference: https://docs.x.com/fundamentals/counting-characters

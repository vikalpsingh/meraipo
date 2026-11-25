# MeraIPO X publishing: configuration, deployment and operations

## Delivered design

Two independent database-backed schedules in MeraAdmin → X publishing:

| Type | Initial time (IST) | Initial state | Publication |
| --- | --- | --- | --- |
| Daily market update | 08:45 | Disabled | OpenAI research; approval first, separate automation opt-in after a successful approved market post |
| IPO opening day | 09:00 | Disabled | One post per eligible IPO, with the same image renderer as opening-day email; approval by default |

The times start generation. They do not promise publication at that exact minute.
Celery Beat checks once per minute. A one-hour catch-up window handles short outages;
after that use Generate next eligible draft. Only one candidate is generated per tick.
No subscription recipients or private email links are sent to OpenAI or X.

The existing deterministic IPO-brief endpoint is retained for compatibility. New scheduled
work uses unique type/date/IPO keys, so the two types cannot suppress one another.
Existing production market/email job configuration is not overwritten.

## 1. OpenAI setup (there is no ChatGPT share-link pull configuration)

The shared chat is a content reference, not a daily market-data API. Its contents could
not be fetched during implementation. Do not enter ChatGPT session cookies or passwords.

1. Create an API project at https://platform.openai.com/ and configure billing, project
   limits/alerts and a server-side API key. ChatGPT UI access alone is not this integration.
2. Save OPENAI_API_KEY in the private server environment (file mode 0600). Never add it
   to NEXT_PUBLIC variables, Git, browser storage, screenshots or frontend build args.
3. Set OPENAI_MARKET_MODEL=gpt-6.2-astra, or a model verified to support Responses,
   web_search domain filtering and strict structured outputs in your account.
4. Recreate backend containers after changing environment values. MeraAdmin shows only
   whether the key is present, never the key or provider response bodies.
5. Enable Daily market update in admin, save its IST time, and Generate next eligible draft.
   Review every number, observation date and linked source, then Approve → Publish now.

The Responses API call uses live web search restricted to NSE, BSE, Nasdaq, S&P Global,
CME, ICE and Reuters. Model-selected facts must reference URLs actually retrieved by the
search tool. Future, undated, unapproved and older-than-96-hour observations are rejected.
The 96-hour ceiling accommodates weekends; it does NOT establish that a quote is the
latest trading session. The administrator must check that before approval.

At 08:45 IST Indian cash indices are prior close, not live. The prompt explicitly labels
this and distinguishes US session dates from publication dates. It researches India,
US, commodities, sector and earnings context but publishes only a short supported subset
that fits 280 weighted characters with clickable sources. The user's long example is
not copied, hardcoded or silently split into a thread. No unsupported investment outlook.

One paid research attempt per day is reserved before the request, max 3 search-tool calls,
3,000 output tokens, 50-second request timeout, no automatic retry. Model output is not
an independently verified feed: automatic market publishing requires a successful manually approved market post and
a separate explicit admin opt-in, as well as the global auto-publish switch. Drafts expire after one hour and on date rollover. Failed research waits
for the next day; do not delete its ledger entry to bypass the spending safeguard.

## 2. X @MeraIPO setup

1. In https://developer.x.com/ create/configure a confidential Web App with OAuth 2.0
   user authentication and write permission. Use official POST /2/tweets access.
2. Register the exact callback:
   https://www.meraipo.com/api/v1/admin/x/callback
   It must match PUBLIC_ORIGIN and X_REDIRECT_URI exactly, including www.
3. Authorize scopes tweet.read, tweet.write, users.read, offline.access and media.write.
   Reconnect an existing connection to grant media.write for IPO images.
4. Put X_CLIENT_ID and X_CLIENT_SECRET in the private backend environment. Preserve
   CONFIG_ENCRYPTION_KEY (at least 32 random characters); changing it invalidates tokens.
5. Set X_ENABLED=true and X_REDIRECT_URI as above. Optionally pin X_EXPECTED_USER_ID.
   Both the MeraIPO username and stored immutable user ID are checked before publishing.
6. Fund API access and configure provider-side spending limits. No auto purchase or
   credit recharge is performed by the app. Image upload and identity reads can cost too.
7. Set X_MONTHLY_POST_LIMIT deliberately: the default 20 is conservative and may not
   cover a full month plus IPOs. X_DAILY_ATTEMPT_LIMIT is the legacy variable name for
   the per-post attempt cap (default 1). Monthly limits count all attempts and failures.
8. MeraAdmin → X publishing → Connect @MeraIPO. Complete consent while signed in as
   the intended account. OAuth state is one-time, session-bound and expires in 10 minutes.

Tokens stay encrypted in PostgreSQL and rotate before expiry. Callback queries are
excluded from app gateway logs; apply the same redaction at any external reverse proxy.

## 3. MeraAdmin activation and checks

1. Check configured exchange calendar year and holiday dates against BOTH NSE and BSE.
   Unknown years fail closed. Weekends and special weekend sessions are excluded.
2. Check IPO ingestion completes before the opening-post time. Only non-demo,
   verified/confirmed opening-day IPOs with approved source hosts and fresh source
   timestamps qualify. X_MAX_AGE_HOURS defaults to 24; guide review limit is 30 days.
3. Save each schedule's Enabled checkbox and Time (IST). Settings survive deployments.
   Disabling a type also blocks its already queued posts at publication time.
4. Generate next eligible draft, inspect source evidence and the image preview.
   Multiple opening IPOs are generated one at a time; repeat manually or let ticks run.
5. Approve and Publish now. This is a REAL PUBLIC POST. Confirm PUBLISHED and open its
   X link. Verify the image and source links on X. Do not use unverified market examples.
6. After a successful approved post, optionally enable automatic opening-day publication.
   For daily market automation, first publish a manually approved market post successfully,
   then enable Include daily OpenAI market drafts. This does not guarantee factual accuracy;
   monitor the saved sources and turn it off if source quality deteriorates.
7. Check the ledger for BLOCKED/FAILED/UNCERTAIN outcomes and safe HTTP/request references.
   Refresh status in admin after worker processing.

Opening images show the IPO upper band, same-day fresh GMP if available, implied price,
company, date and disclaimer. Missing/stale GMP is labelled unavailable. They use the
same renderer as opening emails, but later email generation can legitimately reflect a
newer quote. Prices/GMP are rechecked before X publishing; changes block the saved image.
No implication of a guaranteed listing gain or submitted broker application.

## 4. Deploy

Back up PostgreSQL and record current image tags. Use the existing production compose
files and private env; never replace existing unrelated values. Build api, worker,
scheduler, web and gateway, stop workers/scheduler, then run the migration service:

    docker compose build api worker scheduler web migrate
    docker compose stop worker scheduler
    docker compose run --rm migrate
    docker compose up -d api worker scheduler web gateway

Confirm the actual service names and compose overrides used in your deployment first.
Migration 20261117_x_publishing creates the ledger and encrypted connection;
20261118_x_schedules adds schedules, type/dedupe keys and saved PNGs. Installations already
on the first migration upgrade normally. Pillow is pinned in requirements.lock and is
required for PNG rendering. No schema command sends a post.

Run exactly one Celery Beat. Redis must be available; owner-checked locking serializes
X operations. Verify API health, admin controls, worker logs and current calendar.
The local checks mock OpenAI/X; production credentials, model access, media permissions,
OAuth and actual public delivery require the live smoke check above.

## Recovery and rollback

Posting reservations are committed before network calls. Timeouts/5xx/malformed post
responses become UNCERTAIN; interrupted SENDING becomes UNCERTAIN after three minutes.
Never blindly retry these: inspect @MeraIPO and reconcile the remote outcome first.
Media-upload failures occur before tweet creation and are FAILED. GENERATING interrupted
by a worker crash stays visible and reserved, preventing a second paid research call.

Turn off both schedules and auto-publish; set X_ENABLED=false and recreate backends for
an immediate operational rollback. Preserve the ledger and encrypted token state; revert
application images only to a compatible schema revision. Prefer leaving added columns.
If schema rollback is essential, archive both X tables securely and stop X workers first.
The new downgrade refuses to restore one-post-per-day uniqueness if multiple posts exist
for a date. Never delete published ledger rows casually or restore rotated refresh tokens.
Disconnect clears local tokens; if remote revocation fails, revoke the app in X settings.

## Official references
- https://developers.openai.com/api/docs/quickstart
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code
- https://docs.x.com/x-api/posts/create-post
- https://docs.x.com/x-api/media/upload-media
- https://docs.x.com/x-api/getting-started/pricing

## Pull content for review
Each schedule has a Pull content for review button. This reads stored data only; it
never spends an OpenAI request or publishes. IPO review includes today's non-demo
opening companies, including unverified ones, with individual eligibility checks.
It does not mark their guides verified or refresh the external IPO feed.
Market review shows today's saved research. Future insufficient-evidence results
retain the model's reason and an explicitly unverified preview; older failures cannot
recover previously discarded output. ChatGPT conversations are not imported.
Generate next eligible draft remains subject to the daily research cap. Manual
IPO regeneration is allowed only before publishing attempts, and all manually
generated content stays DRAFT even when automation is enabled.

## Manual connection test posts
MeraAdmin includes a textarea and preview for administrator-entered text. Save manual
draft for review does not send anything. Approve, then Publish now explicitly queues
a real public post to @MeraIPO, using the same identity checks, outbox, attempt caps
and uncertain-send handling. Manual posts do not require an opening IPO or a trading
day, but expire at IST date rollover and can never use automatic approval. Exact
same-day text is deduplicated. Admin-entered claims are not verified market research.
No new database migration is required.

Get today's market-opening draft · OpenAI uses the server Responses API, not a
ChatGPT conversation. Enable and save the market schedule first. It preserves the
one-research-request-per-day safeguard and saves manually requested output for review.
An existing blocked daily request is not retried or replaced by manual text.

## Public-feed IPO automation (opening and closing)
IPO_OPENING and IPO_CLOSING now have independent stored schedules (defaults 09:00
and 09:15 IST, disabled until selected). With the global automatic-publishing toggle
enabled, both queue posts without guide verification, schedule-confirmation flags,
review dates or a previously approved test post. Account connection remains required.
The separate OpenAI automation gate still requires a successful approved market post.

Source selection uses stored IPOProviderDetail provenance, falling back to an existing
source URL or the IPOAlerts provider identity. Accepted public feed hosts are NSE, BSE,
IPOAlerts and IPOWatch (the configured IPOWEB source). Public-feed reminders do not
claim exchange verification. Non-demo data, current event dates, freshness, cancellation
and conflict checks remain enforced. GMP stays explicitly unofficial and stale GMP
is omitted by the shared image renderer. This does not modify email eligibility.

Opening and closing events have separate type/date/IPO duplicate keys, including when
both dates coincide. A blocked, unattempted IPO post can be reconsidered automatically
when its source timestamp changes during the schedule window. Schedule the ingestion
job before the X jobs; a failed sync is not bypassed by changing timestamps. No additional
provider fetch or paid research is performed by the IPO post job. Manual generation
continues to create drafts; automation only applies to scheduled generation.

No migration is needed: schedules are JSON and post kinds are strings. Deploy API,
worker, scheduler and web together. Enable/save both schedules and then enable the
global automatic-publishing toggle. Disable either schedule or the global toggle to
stop future automatic publishing. Existing published/uncertain posts are not retried.

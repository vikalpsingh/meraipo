# MeraIPO SES production deployment

This runbook supersedes the earlier opening-day sender plan. The production alert is **one calendar day before a confirmed listing**, from **MeraIPO Alerts <alerts@meraipo.com>**, with an 08:00–12:00 IST catch-up window by default. This change does not activate bulk sending. No AWS identity, credentials, host deployment, inbox receipt or live SNS delivery has been verified from this workspace.

## Implementation and migrations

- Existing subscription, confirmation, unsubscribe, SES event, worker and aggregate analytics modules are reused.
- `packages/shared/email_template.py`: escaped branded HTML and plain text shared by preview/test/production. Issue price (upper-band assumption if necessary), GMP, assumption-based percentage, subscription multiple and timestamps; missing values are N/A. Public IPO links contain only source/medium/campaign/IPO-slug UTMs. Private unsubscribe tokens never enter those URLs.
- `packages/providers/ses_readiness.py`: read-only SES identity/DKIM/MAIL FROM, production access, quota/rate, configuration-set events and SNS subscription checks. Public SPF/DMARC TXT records are resolved over HTTPS through Cloudflare. Inaccessible checks fail closed and show unavailable, not invented state. Results cache for 60 seconds.
- `apps/api/email_admin.py` and `apps/web/components/email-control-center.tsx`: protected Email Alerts Analytics control centre, status refresh, preview, TEST to signed-in administrator only, signed delivery + inbox acknowledgement, production control, last run and safe failure/retry details. Test mail is excluded from production campaign counts. Requesting a test never opts the administrator into marketing.
- `20261031_email_alerts`: subscription/campaign/delivery/event foundation.
- **`20261101_email_operations`**: campaign scheduled timestamp, attempt/retry/last-event fields, durable `(subscriber, IPO, alert type)` reservations, persistent OFF control, heartbeat/lease/test evidence and dispatch runs. Existing campaign reservations are backfilled without changing subscriber preferences or deleting old messages.

No migration enables sending. Keep existing migrations in order; never edit an already applied migration on production. Apply both if the foundation has not yet been deployed.

## Configuration (private environment file)

Preserve existing database, Redis, market-data, admin and web variables. Add these without exposing secrets in Git or shell history:

```dotenv
ENVIRONMENT=production
DEMO_MODE=false
PUBLIC_ORIGIN=https://meraipo.com
SITE_URL=https://meraipo.com
EMAIL_ALERTS_ENABLED=true
EMAIL_FROM=alerts@meraipo.com
EMAIL_FROM_NAME=MeraIPO Alerts
SES_REGION=ap-south-1
SES_CONFIGURATION_SET=meraipo-ipo-alerts
SES_SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:REPLACE_ACCOUNT_ID:meraipo-ses-events
IPO_EMAIL_SENDING_ENABLED=false
EMAIL_SEND_HOUR_IST=8
EMAIL_CATCHUP_HOURS=4
EMAIL_BATCH_SIZE=20
EMAIL_MAX_PER_SECOND=1
EMAIL_MAX_ATTEMPTS=5
EMAIL_UNSUBSCRIBE_DAYS=400
EMAIL_OPEN_TRACKING_ENABLED=false
EMAIL_EVENT_RETENTION_DAYS=400
```

Retain the existing stable `CONFIG_ENCRYPTION_KEY` and `EMAIL_TOKEN_SECRET` (at least 32 random characters each). Rotating these without a dedicated migration breaks identities, encryption or links. `EMAIL_ALERTS_ENABLED` permits subscription verification/tests; **`IPO_EMAIL_SENDING_ENABLED` is a separate environment permission**, and the persistent admin control also defaults OFF. Set the latter true only after smoke checks; it does not itself turn on the database switch.

## AWS resources and DNS — operator actions

1. Verify SES **domain identity `meraipo.com` in ap-south-1**, including the exact DKIM CNAME values supplied by SES.
2. Set custom MAIL FROM to **alerts.meraipo.com**, with SES-supplied MX and SPF TXT records. This is the envelope sender domain, not the visible From header. Configure `_dmarc.meraipo.com` with your domain administrator; readiness checks record presence, not a security audit of policy strength.
3. Request SES production access and review quota/rate. In sandbox, the administrator test recipient must also be verified.
4. Create configuration set `meraipo-ipo-alerts` and dedicated standard SNS topic `meraipo-ses-events`. Configure SEND, DELIVERY, BOUNCE, COMPLAINT, REJECT and DELIVERY_DELAY to that topic. Keep SES click/open tracking disabled unless explicitly approved; application links use GA4 attribution, and Open recording is optional.
5. Subscribe `https://meraipo.com/api/v1/ipo-alerts/ses-events` as HTTPS, **raw delivery OFF**. The topic must permit SES publishing only from the correct account/configuration set. Application verifies certificate host/signature, exact ARN, header/body message type and timestamps before confirming through SNS API. No arbitrary SubscribeURL is followed.
6. Configure SNS HTTPS retries (HTTP 429/5xx are retryable) and attach a subscription dead-letter queue. Alert on the DLQ. The application accepts signed envelopes up to 24 hours old and deduplicates SNS MessageId; older DLQ events need operator investigation/republication through the trusted topic. Do not discard outages silently.

Readiness cannot create these resources. Keep network access to AWS, SNS certificate endpoints and DNS-over-HTTPS available from the relevant containers.

## Least-privilege credentials

Use the default AWS credential provider chain. Prefer an attached role only where the host actually supports it; do not assume a Lightsail instance has an EC2 instance profile. Otherwise use the private read-only mounts illustrated in `infrastructure/compose.ses.example.yaml`, with separate API and worker profiles. Make files readable only by the relevant container UID/operator. Never place them in the web image, frontend env or repository.

- Worker: `ses:SendEmail` restricted to the verified sender identity and intended configuration set. No arbitrary sender identities. Also read-only checks: `ses:GetEmailIdentity`, `ses:GetAccount`, `ses:GetConfigurationSetEventDestinations`, `sns:ListSubscriptionsByTopic`.
- API: `sns:ConfirmSubscription` restricted to the configured topic; the same read-only SES/SNS checks for the control centre. API **does not need SendEmail** because tests are queued and sent by the worker.
- Scope identity/configuration-set/topic actions to their resource ARNs wherever supported. `ses:GetAccount` requires account-level read scope. DNS checks use public records, not AWS secrets.
- Separate sender IAM from console provisioning permissions. Verify denied send operations are visible as sanitized failures rather than granting broad administrator access.

## Exact deployment sequence for the discovered Compose services

Local repository contains `compose.yaml`; there is no checked-in `compose.prod.yaml`. Review/copy the provided production and SES examples to `/secure/compose.prod.yaml` and `/secure/compose.ses.yaml` on the host, adapting only the existing TLS proxy/credential paths. Keep `/secure/meraipo.env` outside the repository, owned appropriately, mode 0600. The host's existing TLS proxy must preserve POST bodies and `x-amz-sns-*` headers and forward to gateway port 3000. Do not expose PostgreSQL, Redis or API ports publicly.

After committing/reviewing the release and backing up PostgreSQL, assuming the actual checkout is `/var/www/meraipo`:

```bash
cd /var/www/meraipo
git pull --ff-only origin main
# All commands read the private env explicitly; no secrets are printed.
sudo docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml config --quiet
sudo env COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml build api worker scheduler migrate web gateway
# Quiesce old workers so they cannot write an obsolete email schema during migration.
sudo docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml stop scheduler worker
sudo docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml run --rm --no-deps api python -m alembic upgrade head
sudo env COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml up -d --no-build api worker scheduler web gateway
sudo docker compose --env-file /secure/meraipo.env -f compose.yaml -f /secure/compose.prod.yaml -f /secure/compose.ses.yaml ps
curl --fail https://meraipo.com/api/v1/site/features
```

API, worker, scheduler and migrate share the same backend image definition. On a fresh installation, start postgres/redis and run migrations first through the normal Compose dependency chain; the sequence above is for an existing healthy database. Do not run demo seeds or database resets. Existing market tasks pause briefly while workers restart. Keep the gateway available where possible; its maintenance response covers web rebuild transitions.

## Required smoke checks, then explicit activation

1. Sign in to MeraAdmin → Email Alerts Analytics. Refresh readiness. Verify domain, DKIM, MAIL FROM, SPF, DMARC, SNS event destination/subscription, account access and quota. Unknown/inaccessible values are blockers.
2. Verify scheduler heartbeat appears within three minutes. Confirm persistent production sending is OFF.
3. Select an IPO and inspect HTML and plain-text previews. Verify escaped content, correct slug, prices/GMP freshness and unsubscribe controls.
4. **Explicitly click “Send one TEST to my admin email.”** Only your authenticated administrator address is targeted. Preview/test subject is marked TEST; no other subscribers are emailed. Check accepted status and then your actual inbox. Confirm DKIM/SPF/DMARC in received headers.
5. Refresh until signed SNS DELIVERY is recorded, then click “I received this test in my inbox”. The gate requires both delivery feedback and this recipient acknowledgement for the current sender configuration. Test acceptance alone is insufficient.
6. Use the test's unsubscribe link (required by the production gate) and verify it remains available when the public feature is OFF. Confirm that unsubscribing does not silently re-subscribe the address. Register a separate consenting operator address, complete double opt-in and inspect suppression using SES mailbox-simulator events where appropriate.
7. Ensure an operator-verified Applicant Guide has **schedule_status=CONFIRMED and verification_status=VERIFIED** for a non-demo IPO listing tomorrow. Missing/tentative schedules are skipped. Revalidate schedules after feed revisions/cancellation/postponement.
8. Verify duplicate prevention with mocked tests/staging and repeated scheduler ticks. Never bulk-retry uncertain sends or erase reservations to force a resend.
9. Set `IPO_EMAIL_SENDING_ENABLED=true` in the private env, recreate API/worker/scheduler with the same Compose files, enable the email subscription feature if needed, then **explicitly enable production sending in Admin**. Readiness must still pass. Monitor the first morning batch and DLQ/failures.

Do not mark any live check successful unless observed. No real mail is sent by the automated regression tests.

## Dispatch semantics and recovery

- Default window: 08:00 inclusive to 12:00 exclusive IST on the calendar day before listing. The configurable window never extends past midnight. A missed window is skipped, not sent after listing. Queued messages are revalidated at send time.
- Durable uniqueness is per subscriber/IPO/pre-listing type across date revisions. Existing deliveries are also checked. A postponed IPO is not automatically resent to someone already reserved/sent; investigate and design a separate correction campaign if needed.
- A DB lease prevents overlapping batches; atomic row reservation protects against duplicate worker claims. Send rate is the lower of configured rate and SES rate, capped by remaining daily quota and batch/time budget. Use a dedicated SES account or conservatively budget other senders sharing the quota.
- Explicit throttling receives bounded exponential backoff and jitter. Permanent rejections stop. Network/5xx ambiguity becomes UNCERTAIN, with no automatic retry because SES may already have accepted the message. Signed events can reconcile uncertain messages by delivery_id tag/message ID.
- TEST and verification messages can run while bulk is off, but only with server permission and AWS quota. A feature toggle off also pauses confirmation/subscriber messages; unsubscribe always remains reachable. An in-flight SES request may finish after disabling.
- Hard/undetermined bounces and complaints suppress recipients. Soft bounces and delays are separate states. Late SEND/DELIVERY events never erase complaint/bounce state. Public preference links expose neither email nor sequential subscriber ID; unsubscribe is HMAC-authenticated and expires after the configured retention window (default 400 days). Confirmation expires in 24 hours.
- Interrupted sends become UNCERTAIN after 15 minutes, and abandoned runs become FAILED; this maintenance runs even while bulk sending is off.
- Raw events retain the existing retention policy; keep run/ledger history for reconciliation. Apply upstream CDN/APM log redaction to token routes. The gateway and API already redact these paths.

## Rollback

Disable production in Admin first; this action does not depend on AWS availability. Set `IPO_EMAIL_SENDING_ENABLED=false` in the private environment and restart API/worker/scheduler. Preserve database rows, reservations, unsubscribe and suppression state. Roll back to a compatible image digest; avoid rolling back to the old sender without its fail-closed environment switch. Prefer a forward fix for schema changes. Do not drop email tables, reset subscriber preferences or blindly replay UNCERTAIN deliveries. Stop the worker/scheduler temporarily only if the disable control is unavailable; this also pauses market jobs.

## Remaining external blockers

Verified production SSH/host access, AWS credentials/identity/DNS/configuration set/topic, verified administrator recipient/test inbox, SNS delivery feedback and a healthy deployed scheduler are not available in this workspace. Production sending remains OFF until those checks and explicit admin activation are completed.

References: [SES identity](https://docs.aws.amazon.com/cli/latest/reference/sesv2/get-email-identity.html), [SES account](https://docs.aws.amazon.com/cli/latest/reference/sesv2/get-account.html), [SNS HTTPS retries](https://docs.aws.amazon.com/sns/latest/dg/sns-message-delivery-retries.html).


## Verification completed in this workspace

- 32 focused backend cases passed across the email, production-operations and feature modules (the operations module was rerun after verifying persisted recovery state).
- 9 focused UI cases passed for consent, feature controls, disabled production activation, preview and explicit TEST requests.
- TypeScript, targeted Python/TypeScript lint, migration-head inspection, `git diff --check`, and combined base/production/SES Compose configuration validation passed.
- Migration upgrade/downgrade was exercised on isolated SQLite. A live PostgreSQL migration, full regression/CI, browser-based visual verification, actual SES send/inbox/SNS feedback and Lightsail rollout remain release checks; none is represented as completed.
- Observed local configuration: email service OFF, bulk permission OFF, no SNS topic, no email token secret and no local SDK credentials. No production switch was enabled and no real email was sent.

Focused verification commands (run from repository root; frontend commands from `apps/web`):

```bash
python -m pytest tests/test_email_alerts.py tests/test_email_operations.py tests/test_features.py -q
node node_modules/vitest/vitest.mjs run tests/unit/email-control-center.test.tsx tests/unit/email-alerts.test.tsx tests/unit/feature-controls.test.tsx
node node_modules/typescript/bin/tsc --noEmit
```

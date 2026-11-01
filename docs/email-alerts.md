> Production update: use [SES production runbook](ses-production.md). It supersedes the historical opening-day plan below with confirmed pre-listing alerts at 08:00 IST, alerts@meraipo.com, and a separate fail-closed production switch.

# Email subscriptions and traffic analytics

## Delivered

- `/email-alerts` is linked in the public footer. Registration requires explicit consent, then a confirmation valid for 24 hours. Repeated registration does not create duplicate subscribers or confirmation messages within 24 hours.
- A separate Celery task prepares a reminder on the opening day of each non-demo IPO, after `EMAIL_SEND_HOUR_IST` (default 09:00 IST). It checks the opening date again before sending. Existing market tasks and schedules are unchanged.
- Unique subscriber/campaign constraints and atomic pending-message claims prevent repeat sends. The task processes five messages per minute (at most 300/hour per active scheduler). Capacity must be reviewed before a large launch. Ambiguous SES outcomes become `UNCERTAIN` and are never automatically resent.
- MeraAdmin → **Email Alerts Analytics** provides IST date filters, aggregate metrics, subscriber growth, funnel and traffic charts, sortable/paginated IPO performance and queue counts. No subscriber addresses appear in these responses.
- Click URLs use unguessable HMAC tokens and redirect only to stored company IPO slugs on the configured public origin. Bot/preview events are classified; remaining requests are **unclassified**, not proven human visits.

## Deployment

1. Back up PostgreSQL. Deploy backend and web together; run `python -m alembic upgrade head` (new revision `20261031_email_alerts`). Compose's migrate service already does this before API/worker start. Do not enable sending before the migration and notification endpoint are ready.
2. Keep the MeraAdmin email alerts feature toggle OFF initially. Set stable, separate random `EMAIL_TOKEN_SECRET` and `CONFIG_ENCRYPTION_KEY` values of at least 32 characters through your secret manager. Do not rotate either casually: the former identifies subscribers and generates links; the latter decrypts stored addresses. Use the exact public HTTPS origin, without a trailing slash, for `PUBLIC_ORIGIN` and `SITE_URL`.
3. In Amazon SES, verify your sending domain, configure DKIM/SPF/DMARC, obtain production sending access and choose `EMAIL_FROM`. Set `SES_REGION`, `SES_CONFIGURATION_SET` and a dedicated `SES_SNS_TOPIC_ARN`. Attach the configuration set's Send, Delivery, Bounce, Complaint, Reject and DeliveryDelay events to that SNS topic. Subscribe HTTPS endpoint `https://<your-domain>/api/v1/ipo-alerts/ses-events`. Signature-verified subscription confirmation uses `sns:ConfirmSubscription` for this topic only. Grant worker `ses:SendEmail` for the sender/configuration set and API `sns:ConfirmSubscription` on that topic using the AWS SDK credential chain / IAM role. Topic policy must restrict publishing to your SES account.
4. If open tracking is desired, enable SES Open events AND `EMAIL_OPEN_TRACKING_ENABLED=true`. Otherwise keep SES open tracking off. Open rates are affected by privacy proxies and cannot prove human reading. SES click tracking should stay off; the application owns click redirects.
5. For Docker, attach the IAM role/credential provider appropriate to the host. Compose intentionally does not embed AWS credentials. For local testing, pass SDK credentials only via a private override or secrets mount. Restart API, worker and scheduler after configuration; enable the MeraAdmin email alerts feature toggle when ready. Keep a single beat scheduler. The migration never enables email sending.
6. Verify using your own consenting test address: register, receive confirmation, explicitly confirm, check a fixture IPO opening today, receive one reminder, click and unsubscribe. Verify signed SNS delivery/suppression callbacks and dashboard counts. No real subscriber emails are sent by the regression tests.

## Optional GA4

- Configure a GA4 property with reporting timezone Asia/Kolkata. Set web `GA4_MEASUREMENT_ID` and backend `GA4_PROPERTY_ID`.
- Enable Google Analytics Data API, grant a service account Viewer access to the property, and mount its JSON key read-only in the API container. Set `GA4_SERVICE_ACCOUNT_FILE` to that **container path** using a private Compose override. Never put the key in the repository or web/public directory. Example override volume: `/secure/ga4.json:/run/secrets/ga4.json:ro` on the API service.
- **Disable Enhanced Measurement and automatic page-view/history tracking in the GA4 web stream.** This application sends manually sanitized page views; automatic click/form/search events could expose private input. Do not enable Google Signals or user-provided data collection.
- The Google script loads only after explicit analytics consent. Admin and subscription/preference pages are excluded. Attribution forwards only the fixed email source/medium/campaign and the public IPO slug, with no email, token, name, arbitrary query parameters or user ID. Consent can be changed in the footer.
- Data API queries session source/medium and campaign, with separate reports for daily traffic, IPO identifier, landing page and returning users. Reports cache for 60 minutes. Google reporting can be delayed; sampled or thresholded reports are shown as unavailable rather than exact counts; returning users are GA4's definition, not a demonstrated later visit caused by an email.
- Missing credentials, incompatible reports and service failures return N/A. Clicks are never substituted for sessions. Service account credentials stay server-side.

## Metric reconciliation and operations

Email rates use the cohort of **ALERT messages accepted by SES within the selected IST date range**, with outcomes received to date. Verification messages are excluded. Delivered requires a signed SES Delivery event. Open numerator is delivered messages with an Open event; click/unsubscribe numerators are distinct recipients in that delivered cohort. Thus rates can differ from totals of individual IPO rows when recipients receive several IPO emails. Total click events use occurrence dates and include separately identified suspected scanners. GA4 sessions use activity dates and can include older messages; the funnel is not a strict person-by-person cohort.

Daily growth counts registrations and cumulative first verification, including people who later unsubscribe. Current active subscribers exclude unverified, unsubscribed and suppressed addresses. Raw click/provider events are purged by the email task after `EMAIL_EVENT_RETENTION_DAYS` (default 400). Ledger/preferences remain for deduplication and reconciliation. For a verified deletion request, an operator must remove dependent raw events and deliveries before deleting the subscriber; do not delete unsubscribe suppression merely to re-import the address. Configure a retention review before public launch.

Investigate `UNCERTAIN` against SES events using delivery_id tags/message_id before any manual retry. Never blindly reset this status. Permanent/undetermined bounces and complaints suppress the subscriber; transient bounces do not. A subscription confirmation cannot replay to undo a later unsubscribe. GET unsubscribe links only display a confirmation page; RFC8058 one-click POST is supported.

API structured logs redact email paths. Uvicorn access logs are disabled in the production image, and gateway access logs exclude token routes. Apply equivalent redaction at any CDN, load balancer, APM and external proxy. Do not serve production with Next dev logging. Keep contact/deletion information on the privacy/contact pages accurate.

## Validation

Focused coverage is in `tests/test_email_alerts.py`. Run only this file for email regression checks; the full suite is intentionally separate. It covers canonical UTMs, redirect allowlisting, IST dates, denominators, signup deduplication, confirmation replay, click classification, event deduplication/suppression, protected analytics, missing GA4, SNS untrusted certificate URLs and sender idempotency. Live SES delivery and GA4 data require configured provider accounts and a consenting operator test.

Official integration references:
- https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message-verify-message-signature.html
- https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html
- https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema

Validation performed: 19 focused backend tests and 7 focused UI tests passed; frontend TypeScript, component lint, Python lint and Compose configuration checks passed. No full regression suite or live SES/GA4 delivery test was run.

## Opening-day GMP alerts and MeraAdmin toggle

MeraAdmin → Feature releases → **IPO opening-day email alerts** controls public signup and the worker. New installations default OFF. The toggle can be changed without a server restart. Valid SES configuration is still required to send mail. Disable pauses queued mail (an SES request already in progress may complete); confirmation/unsubscribe links and analytics remain available. Re-enable sends only reminders still scheduled for the current opening day; obsolete listing reminders are cancelled.

The opening-day message includes the most recent stored GMP observation no later than send time, amount in rupees, observed time in IST, provider and a stale label using `GMP_TTL_HOURS`. Missing GMP is explicitly unavailable; zero and negative GMP remain valid values. The email does not claim GMP predicts or guarantees listing performance. Campaign attribution is `ipo_opening`; historical `ipo_prelisting` links/reports remain supported.

Use `EMAIL_FROM=IPO@meraipo.com` once that address or the `meraipo.com` domain is verified in SES in the sending region. Public recipients need SES production access; sandbox sending is limited to verified recipients. Sending through SES does not create an inbox for replies: provision that mailbox separately if replies should be received. The local workspace currently has no sender/SES credentials configured, so live sender verification or delivery has not been confirmed.

## Configured website Google tag

The public website uses measurement ID `G-ZYEKCCV3J5` through the existing single `AnalyticsConsent` component. It loads only after analytics consent, tracks sanitized public page views on navigation, and excludes admin/email-preference pages. No second inline snippet is needed. `GA4_MEASUREMENT_ID` overrides the default; an explicitly empty value disables the tag. Restart/redeploy web to apply environment changes.

This measurement ID enables browser collection, not server-side reporting access. MeraAdmin traffic reports still require the numeric `GA4_PROPERTY_ID` and a server-only service-account credential file. After deployment, allow analytics and verify the visit in this property's Realtime report. Live receipt has not been verified from this workspace.


## Opening-day GMP subscriptions

Apply migration `20261101_email_preferences` before deploying the API/worker changes.
The public **IPO Alerts** navigation tab opens `/email-alerts`, gated by the existing email feature toggle. The colourful signup and current-open-IPO GMP examples are displayed inline. The homepage no longer opens a popup or writes the old popup preference cookie.
First/last names and email are required; phone is optional. A single GMP band is mandatory.
Contact data and pending verification profiles are encrypted. Confirmation applies a staged
preference update; posting another person's email cannot overwrite their active preferences.
No contact details enter analytics or public URLs. Phone is not used for calls or SMS.

New subscribers receive `ipo_opening` alerts only, from the configured IST send hour until
midnight on the confirmed, verified IPO opening date. GMP is divided by the upper price band:
white subscribes to ALL IPOs including missing/stale GMP; light green subscribes to >20%, strong green to >40%, and gold to >100%. These are cumulative subscription thresholds, separate from exclusive homepage row colours.
The latest nonfuture snapshot is rechecked before dispatch. A changed band defers the pending
message for ten minutes; it can send only if it matches again on the same opening day.
There is at most one accepted alert per subscriber/IPO/campaign kind; ambiguous SES sends
retain the existing no-automatic-retry policy. All existing suppression and production gates apply.
Legacy subscribers with no selected band retain pre-listing alerts until they confirm a new
preference. No preferences are inferred or backfilled. Existing subscribers can use the same
form to request a confirmed change. A pending confirmation stores the latest submitted profile without sending another email within 24h. The existing confirmation link applies that latest profile.

Deploy migration, API, web and worker together. Do not enable public signup until SES readiness,
admin test delivery and production controls have been reviewed as documented in `ses-production.md`.

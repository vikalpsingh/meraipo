# Opening and closing-day IPO application reminders

MeraAdmin → Email control centre → IPO application reminders is visible without
expanding advanced diagnostics. Choose opening day, last application day, or both;
save a time in Asia/Kolkata (including 08:30). Default remains opening day at the
existing server hour (09:00 unless configured otherwise). Saving does not enable
production dispatch or bypass its readiness checks.

Apply migration `20261119_email_schedule` before recreating API and worker containers.
This checkout also contains the preceding X integration migrations; deploy the tested
revision and all its dependencies together. Back up the database first. Existing
production schedule values are not overwritten by defaults. Rollback: stop workers,
restore compatible prior app images, retain the extra JSON column and delivery ledger.
Only remove the new column with the migration downgrade after stopping new code.

## Daily behavior

- The minute worker starts during the configured time and bounded catch-up window
  (`EMAIL_CATCHUP_HOURS`, default four hours, bounded by the same calendar day).
- Eligible IPOs require non-demo company data and OPEN/UPCOMING status. Dates may
  come from a verified/confirmed applicant guide OR a supported published feed
  (IPOALERTS, IPOWEB, NSE, BSE) with valid opening/closing dates and a source timestamp
  no older than `EMAIL_IPO_MAX_AGE_HOURS` (48 by default, configurable 1–72).
  Imported records do not need a manually authored guide. Future timestamps,
  flagged data conflicts, cancelled, postponed and withdrawn issues are excluded.
- Opening-day mode matches open_date; last-day mode matches close_date. Both mode
  takes their union. An IPO opening and closing on one day appears once.
- Render each matching IPO once, then assemble four cumulative GMP-category snapshots.
  All IPOs includes missing/low GMP; other categories require above 20%, 40%, or 100%.
  Persist immutable HTML/text/images in PostgreSQL. Changes to settings or GMP after
  this first snapshot apply to the next daily snapshot, not a duplicate same-day send.
- The outbox adds up to 200 recipients per category per tick. A unique subscriber/date
  key prevents duplicates across ticks and restarts. Eligibility and saved subscriber
  category are rechecked at sending; changed preferences cancel the stale delivery.
- Each recipient receives one combined email with their own unsubscribe token and
  delivery ID. Both-days mode sends again on the distinct closing date, not every day
  between opening and closing. Provider acceptance is not inbox receipt.

## Fixed-recipient end-to-end test

Save the mode/time, then click **Send today's combined test**. The server fixes the
recipient to `meshanti.singh@gmail.com`; the client cannot override it. It assumes
All IPOs for this test only, combines today's eligible issues using the saved mode,
and uses the production rendering, durable outbox and SES sending path. It bypasses
the scheduled time and production-dispatch switch but still requires a configured
verified sender, HTTPS and token secret, and respects recipient suppression.

It never confirms a subscriber, changes their category, creates production digest
reservations or enables sending. Empty/unverified eligibility returns an actionable
error and sends nothing. Test requests have a five-minute cooldown. Click **Check test
delivery** to distinguish queued, SES-accepted, delivered or failed. TEST emails are
excluded from subscriber campaign counts. This button does not replace the separate
readiness inbox/unsubscribe verification workflow.

## 26 November 2026 production diagnosis and recovery

Production dispatch was enabled, SES readiness passed and three confirmed subscribers
were active. The configured mode was both days at 09:00 IST. On 25 November the
morning dispatcher completed 240 ticks with zero processed messages and no alert
campaigns. The candidate IPOs had no applicant-guide rows, so an inner join excluded
them before rendering. The guide-only eligibility condition was a second blocker.
Both scheduler and admin test now use an optional guide and the source policy above.
When date-matching candidates all fail eligibility, the dispatch records
`IPO_REMINDER_SOURCE_NOT_READY` instead of a silent zero-message success.

Deploy this revision together with the IPO sync/Redis lifecycle fixes, recreating
API, worker and scheduler with the existing production environment. No new migration
or SES setting is required for this fix. Run IPO sync successfully to refresh source
timestamps: production records were also stale because the import failed. Verify
the existing both-days/09:00 configuration and use the combined test before the next
scheduled window. Old opening-day messages are not sent retrospectively after their
window; upcoming closing-day reminders still qualify on their closing date.

## Scaling and BCC decision

Content is generated once, persisted for recovery, and reused from the worker's
per-batch campaign cache. Memory alone would lose the snapshot on restart. Messages
are individually addressed, not one shared BCC message: everyone needs a private
unsubscribe link and independent bounce/suppression/delivery state. AWS recommends
one recipient per destination for this use case:
https://aws.amazon.com/blogs/messaging-and-targeting/how-to-send-messages-to-multiple-recipients-with-amazon-simple-email-service-ses/

The default EMAIL_BATCH_SIZE=20 and minute ticks imply approximately 50 successful
batches for 1,000 recipients; this is capacity arithmetic, not a live throughput claim.
EMAIL_BATCH_SIZE can be increased up to 100 after checking SES quota/rate and worker
latency. EMAIL_MAX_PER_SECOND and SES quota cap dispatch. Do not increase concurrency
by bypassing the outbox lease. Retry throttling; reconcile uncertain sends instead
of blindly retrying. Existing test/confirmation backlog and provider latency affect
completion time. Monitor pending, accepted, delivered and failed separately.

Local verification uses an isolated 1,000-subscriber scheduling test, mixed opening/
closing category tests, a mocked fixed-recipient SES outbox test, and admin UI tests.
No real subscriber emails are sent by automated tests.

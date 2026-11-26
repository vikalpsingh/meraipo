# Quarterly-results X publishing

MeraAdmin → X publishing has IPO publishing, Market updates and Quarterly results
sections. Each retains draft review, Approve and Publish now. Public publishing is
real, including tests. Existing IPO/market schedules are preserved.

## Company test
1. Select Quarterly results and enter the full company name or exchange symbol.
2. Generate company results test. OpenAI searches official NSE/BSE filing sources
   for the latest quarterly result declared within 90 days. The requested company
   must match the normalized company name or symbol returned by research.
3. Review the scan report and company row, official filing links, declaration date,
   basis, both quarters and raw amounts. Growth is calculated with Decimal in the
   backend, not accepted from GPT. Tests do not publish automatically.
4. Both revenue from operations and PAT must increase strictly MORE than 20% QoQ.
   Prior denominators must be positive; zero/negative bases, annual/YTD periods,
   non-consecutive quarters, basis mismatch and unverifiable sources are blocked.
   Exactly 20% does not qualify. Values must use INR crore consistently.
5. Approve a qualifying draft, Publish now, refresh and inspect its public X link.
   A nonqualifying result remains visible but cannot be approved or published.

## Scheduled daily declarations
1. Enable Today’s quarterly results · OpenAI and save its IST start time (default
   18:30). Declarations can occur on non-trading days, so this scan runs daily.
2. After a successful approved results test/post, enable the results auto-publish
   option. Also enable the global automatic-publishing switch. Both are required.
3. The existing minute scheduler checks the saved time with a one-hour catch-up
   window. One research scan per IST day selects only declarations dated today IST.
4. It creates a separate post per qualifying company. Where multiple records for a
   symbol appear, use the latest quarter, preferring consolidated. A symbol/quarter
   duplicate key prevents repeated publication. Exact text duplication across tests
   and scheduled posts is also blocked by the existing content guard.
5. Disable the results schedule to stop scans AND publication of queued scheduled
   result posts. Disable results automation to stop unapproved automatic dispatch.

## Spending and coverage
One daily discovery request; at most ten researched companies per request, up to five
web-search calls and 6,000 output tokens. This is a bounded research snapshot, not an
exhaustive exchange feed. Later declarations after the scan are not included that day;
choose a suitable evening time. Company tests are capped at five per IST day, with
repeated same-company requests loading the saved scan. Failures/interrupted research
remain reserved to avoid duplicate charges. A scan and its child posts are persisted
before publication. Existing monthly X caps and uncertain-send safeguards remain.

OpenAI extracts values from retrieved official source URLs, but extraction can still
be wrong. Successful retrieval/date checks are not an independent filing audit.
Review the first results and monitor evidence before enabling automatic publication.
No financial database values are overwritten by this research integration.

## Deployment and rollback
No migration is required: existing JSON schedules and X ledger hold the new kinds.
Deploy API, worker, scheduler and web together with the existing private environment
and Compose options. Preserve encryption keys and tokens. Results defaults disabled;
no live posts are sent merely by deploying. To roll back, disable results schedule
and automation, then restore compatible images without deleting the X ledger.

Local tests mock OpenAI/X. Production research access, billing and actual public
publishing must be checked using the explicit administrator test flow above.

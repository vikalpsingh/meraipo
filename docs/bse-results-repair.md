# BSE results repair — 10 October 2026

## Scope and operation

The automatic BSE job selects companies with a persisted BSE scrip code and no
NSE identifier. Dual-listed companies remain owned by the NSE job; their BSE
pending attachments are excluded too. Combined results runs execute NSE first.
Existing default daily schedules remain NSE 21:00 and BSE 22:00 IST, using the
shared FIFO writer queue. Manual BSE imports remain available for reviewed data.

BSE landing initialization is best effort. Results CSV, company announcements,
result details and attachments have independent stages. Request compatibility
was compared with `bse==3.3.3` in `/tmp/bse-compare` inside the worker container.
Production requirements.lock is unchanged. The maintained package uses a newer
User-Agent, same-site request context and JSON Accept headers; its constructor
does not require the landing page. The jugaad implementation also explicitly
skips its blocked landing page. Sources:
- https://github.com/BennyThadikaran/BseIndiaApi/releases/tag/v3.3.3
- https://raw.githubusercontent.com/BennyThadikaran/BseIndiaApi/master/src/bse/BSE.py
- https://raw.githubusercontent.com/jugaad-py/jugaad-data/master/jugaad_data/bse/live.py

The announcements adapter uses `AnnSubCategoryGetData/w`, tracked `strscrip`,
explicit date bounds, all categories and complete ROWCNT pagination. It accepts
published results/integrated financial filings, excluding board-meeting
intimations. Page repetition or inconsistent totals prevent checkpoint advance.
The default window is 14 days, extended backwards to an older company checkpoint
with three days overlap after outages. Explicit backfills retain supplied dates.
Announcement IDs, timestamp and attachment metadata distinguish revisions;
changing display order or archive location does not create another filing.
Originals retain checksums, and publication preserves period/basis/revision
separation and exact decimal amounts. HTML denial pages are never financials.
A details response without a trustworthy filing timestamp remains in review.

`result_diagnostics` retains stage, actual HTTP status, sanitized URL (no query),
redirect chain, MIME type, elapsed time, response reference IDs and a bounded
sanitized error excerpt. It never records request cookies or authorization.
Admin job-run detail shows these diagnostics. 403 and 406 are separate errors;
neither is retried. 429 persists Retry-After. Requests are sequential and bounded.
A denied route is stopped for the run while independent sources remain usable.

## Official company fallback

In MeraAdmin → Data & scheduler → results review, expand Approved company
investor-relations fallback. Select a BSE-only company, confirm the official
page, and configure a same-host document directory ending in `/`. Approval is
audited. Only links discovered in that approved directory are fetched. HTTPS,
public DNS and exact origin are checked at each request, and the validated IP
is pinned while TLS still verifies the hostname. Redirects cannot escape the
approved page/directory or reach internal addresses.

Original files enter the existing identity/period/basis/unit parser. PDF,
unsupported taxonomy or missing publication date stays in review. An admin can
create a manual filing with the approved document URL and verified publication
date, upload its original, preview and publish using existing controls. No
company source is automatically declared official based on a name search.

## Files

- packages/providers/result_http.py: bounded session and diagnostic evidence.
- packages/providers/bse_results.py: announcement filtering and pagination.
- packages/providers/company_results.py: approved IR discovery and safe fetch.
- apps/worker/bse_results.py: BSE-only orchestration and checkpoints.
- apps/worker/company_results.py: independent fallback processing.
- apps/worker/results.py: integration, stable filing identity, parser events.
- packages/database/models.py and migration 20261010_bse_diagnostics: persistence.
- apps/api/result_routes.py and job_routes.py: approval and diagnostic endpoints.
- apps/web/components/{official-results-source,results-console,job-history}.tsx:
  approved-source UI and job evidence.
- apps/web/app/page.tsx: Open → Coming next → Closed tabs; Announced below.

## Deployment and focused verification

Database backup: work/meraipo-before-bse-results.dump.

```powershell
docker compose build api worker scheduler migrate web
docker compose run --rm migrate
docker compose up -d api worker scheduler web gateway
.venv/Scripts/python.exe -m pytest tests/test_bse_results_repair.py tests/test_results_importer.py tests/test_job_operations.py -q
cd apps/web
node node_modules/vitest/vitest.mjs run tests/unit/ipo-stage-tabs.test.tsx tests/unit/job-operations.test.tsx
```

Mocked tests cover optional failed landing, per-stage denial diagnostics,
Retry-After, empty responses, pagination, BSE-only scope, XBRL publication,
revisions, idempotency, API display, IR approval and SSRF prevention. The XBRL
fixture is a retained NSE-format SEBI filing used to exercise the common parser;
it is not evidence of a live BSE result being published.

Live verification details are appended after the deployment checks below.


## Live verification (existing Docker worker, 10 October 2026)

- Runs `fbf576f2-d781-4433-8f20-82f5200763e4` and
  `04150a46-c338-480e-9d75-c24dda45056c` both completed SUCCESS, zero failures.
- Explicit discovery range: 1 July–10 October 2026. Twelve BSE-only companies
  were checked; sixteen companies with NSE identifiers were excluded.
- Landing page, today's CSV, all twelve announcement requests and all twelve
  result-detail requests returned HTTP 200. CSV contained nine rows, but there
  were no matching financial filings for the tracked BSE-only companies.
- Both runs published/downloaded zero financial records. This proves restored
  discovery and an empty idempotent rerun, not live financial publication.
- An independent download used an actual returned FX Multitech attachment URL:
  https://www.bseindia.com/xml-data/corpfiling/AttachHis/aebf9a61-8b3c-43cc-a6fd-fdfb703dec8d.pdf
  It returned HTTP 200, application/pdf, 515814 bytes, valid PDF signature;
  SHA256 `5df1e99af903fcebdc004bb363f69f4a6d566459ad1479398fdeea50ceb44427`.
  This is a compliance certificate, NOT financial results; it was deliberately
  excluded from financial storage/publication. Probe original retained in
  work/bse-live-original-probe.pdf. Diagnostics retained in the database and
  work/bse-live-verification.json (two JSON lines: run summary, events).
- Admin browser check verified the approved-source controls and 28 stage
  diagnostics for the successful rerun. No live official company fallback was
  configured because no approved IR source was supplied. Its download, parser
  routing, approval and public-IP enforcement are covered by mocked tests.
- Parsed period, basis, INR units, revenue/PAT, database revisions and Company
  Details display are verified using local fixtures, not live BSE financials.
- Home page browser check confirms Open → Coming next → Closed tab order.
- Migration head: 20261010_bse_diagnostics. Production dependencies unchanged;
  temporary bse 3.3.3 comparison environment was isolated in the old worker and
  removed by container recreation. No browser automation is needed in the job.

Final focused checks: 57 backend test cases and six UI cases passed across the
results, operations and home-tab test files. Production web build and TypeScript
checks passed. `alembic check` reports no new upgrade operations. An additional
PDF review test confirms a retained, unparsed PDF gives review-required counters
and a partial job outcome, with zero published results. Retry-After defers pending
BSE downloads as well as discovery.

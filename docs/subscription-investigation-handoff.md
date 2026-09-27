# Subscription investigation — 27 September 2026

## Task still unfinished
Find and fix missing subscription percentages for Green Asia Impex, Peshwa Wheat, Roopa Screen, Bench Mark Infotech Services and Himalayan Solar. No implementation changes made in this investigation yet. Preserve all existing uncommitted changes. Do not expose .env secrets or reset admin credentials.

## Verified database findings
- Green Asia (GREENASIA), Bench Mark (BMISL), Himalayan Solar (HIMALAYAN): stored NSE_CONSOLIDATED snapshots exist, dated 25 Sep 2026 17:00 IST. Their category offered_shares are zero; multiples correctly null. Bid shares exist. This is not evidence of lost database writes.
- Raw Green Asia payload ID ae700325-2d8b-4efb-83f3-5b304f483b6f: ipo-active-category response has zero offered quantities for QIB, NII and Total, no individual-investor row, NII and total bids 14400. It may be the wrong endpoint for current SME demand: verify SME-specific official bindings.
- Bench Mark raw cdf09b14-85ea-4165-8b3e-ca560fb65b08: NII/total bids 147600, offered zero.
- Himalayan raw 9ca8b457-0311-4999-9fa7-544a58a3b627: QIB bids428400, NII798000, total1226400, offered zero.
- Roopa: BSE_SYMBOL ROOPA, BSE_ISSUE7997; Peshwa: BSE_SYMBOL PESHWA, BSE_ISSUE8000. Neither has subscription records.
- Scheduler collect() currently loops only BSE_IPO_ISSUES_JSON manual configuration, not stored BSE_ISSUE identifiers. Confirmed collection coverage gap.
- BseIpoProvider legacy URL CummDemandSchedule.aspx?ID=7997&status=L returns301 to https://www.bseindia.com/markets/publicIssues/CummDemandSchedule?ID=7997&status=L. Downloader rejects redirects. Replacement page likely JS app: do not assume old HTML parser works.

## Research next steps
Official BSE IPO page returns200 and references /assets/includenew/js/main-ICDVFOXQ.js (as observed27Sep2026). Inspect official component bindings to find actual subscription endpoint and correct identifier semantics before implementing automatic collection. Never guess issue IDs or sum overlapping exchange/consolidated snapshots.
Official NSE issue page https://www.nseindia.com/market-data/issue-information?symbol=GREENASIA&type=Active&series=SME responds200 with MeraIPO User-Agent. Inspect all script references (last20 previously printed did not include issue-specific module). Verify SME bid/allocated-share source, timestamps and category semantics.
NSE official FAQ https://www.nseindia.com/static/trade/e-ipo-faqs confirms SME Individual Investor category replaces Retail; exactly2lots versus larger applications classified NII. Do not silently map this to retail without correct labeling.

## User constraint
Only calculate category subscription using verified allocation for that category. Otherwise leave blank with ** explanation. Never divide category bids by total IPO offered shares. Never fabricate missing percentages or treat unknown as zero.

## Relevant code and checks
- packages/providers/nse_subscriptions.py; packages/providers/bse_ipo.py; packages/providers/ipoalerts.py; apps/worker/exchange_pipeline.py; apps/api/repository.py.
- models Subscription, SubscriptionDay, SubscriptionDetail, MarketStage, RawPayload, JobError.
- .venv/Scripts/python.exe -m pytest (not pytest.exe). Existing tests/test_nse_subscriptions.py, test_exchange_pipeline.py, test_market_data_recovery.py, test_subscription_gaps.py.
- Repo C:/Coding/meraipo, local Docker http://localhost:3000; backend docker compose exec -T api python - with script stdin. Docker requires approval escalation. Never print environment/secrets.
- Latest inspection command was not executed: automatic approval review reported usage limit. This was a review service failure, not an unsafe-action decision. Do not bypass approval.

## Completion required
Implement verified collection/parser fixes and per-company job diagnostics, add regression tests, run collection, trace staging to master to public API, report precisely which values populated and which still unavailable. Do not claim beta data complete unless verified.

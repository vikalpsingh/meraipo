# Data model

Company -> identifiers, IPO, financial periods/results, EOD prices and valuation snapshots. An IPO has dates, documents, subscriptions, GMP history and a separate immutable baseline. Quarterly revisions and admin audits preserve corrections. Every core value may reference field-level provenance (source, URL, observed/fetched/verified timestamps, verification state). Null represents missing information, never zero.

PostgreSQL owns constraints, foreign keys and decimal precision. Core financial entities use typed columns. JSON is limited to audit diffs, provider payloads and legitimately variable diagnostics. Future users/applications are schema-only; V1 exposes no account or portfolio workflows.

Indexes follow slug, ticker/exchange, listing date/status, company-period, price date, source timestamps and trend lookups. Initial migrations are immutable after release; append new migrations. The original D1 prototype must be exported and mapped explicitly before any production migration; it is not silently reused.

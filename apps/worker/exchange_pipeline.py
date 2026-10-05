"""Collect into staging; publish separately under the shared database writer lease."""

import json
import time
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, or_, select, update

from apps.worker.market import (
    acquire,
    india_today,
    ingest_record,
    match_company,
    reconcile_lifecycle,
)
from packages.database import models as m
from packages.providers import exchanges as ex
from packages.providers.market import (
    FeedConfig,
    FeedError,
    configuration,
    fetch_feed,
    fingerprint,
    normalize_record,
    safe_url,
)
from packages.shared.config import settings
from packages.shared.job_schedules import EXCHANGE_JOBS, SCHEDULED_JOBS, job_parameters

PIPELINE_JOBS = {
    "sync-ipos": ("IPO, subscription & GMP sync", "23:00 daily", ["ipos", "subscriptions", "gmp"]),
    "sync-prices": ("Daily closing price sync", "19:00 daily; retries 20:00 and 22:00", ["prices"]),
    "sync-results": ("Quarterly result sync", "19:30 daily (configurable)", ["results"]),
    "collect-ipos": (
        "Collect IPOs & subscriptions",
        "07:00 daily",
        ["ipos", "subscriptions", "gmp"],
    ),
    "collect-prices": ("Collect daily closes", "18:45 trading days", ["prices"]),
    "collect-results": ("Collect quarterly results", "21:00 Friday", ["results"]),
    "publish-ipos": (
        "Publish IPOs & subscriptions",
        "07:15 daily",
        ["ipos", "subscriptions", "gmp"],
    ),
    "publish-prices": ("Publish daily closes", "19:00 trading days", ["prices"]),
    "publish-results": ("Publish quarterly results", "21:30 Friday", ["results"]),
}
PIPELINE_JOBS.update(
    {
        name: (label, "Configurable · IST", [kind])
        for name, (label, kind, _) in EXCHANGE_JOBS.items()
    }
)


async def raw_payload(db, provider, kind, url, raw):
    row = m.RawPayload(
        provider=provider,
        data_type=kind,
        requested_url=safe_url(url),
        http_status=200,
        payload_text=raw,
        payload_hash=fingerprint(raw),
        parser_version=ex.VERSION,
    )
    db.add(row)
    await db.flush()
    return row


def error(db, run, provider, item, exc):
    from packages.shared.job_diagnostics import GUIDANCE

    code = str(exc) if isinstance(exc, FeedError) else type(exc).__name__
    guidance = {
        "IPOALERTS_AUTH_FAILED": "IPOAlerts rejected the API key (401/403). Set a valid IPOALERTS_API_KEY on the backend and restart API/worker/scheduler. Existing data is retained.",
        "IPOALERTS_KEY_REQUIRED": "Set IPOALERTS_API_KEY on the backend; preview access is not a complete market feed.",
        "IPOALERTS_INCOMPLETE_ACCESS": "IPOAlerts returned restricted preview data. Verify API key and plan access; this response was not published.",
        "IPOALERTS_RATE_LIMITED": "IPOAlerts rate limit reached. Wait for the provider quota to reset before rerunning.",
        "IPOALERTS_SCHEMA_CHANGED": "IPOAlerts response or pagination metadata failed validation. Review the provider API contract.",
        "IPOALERTS_INVALID_ROW": "The IPOAlerts record failed validation. Review its provider ID and retained raw response.",
        "IPOALERTS_INVALID_GMP": "The GMP quote has an invalid value or observation timestamp. IPO master data is retained; no zero or fresh timestamp is invented.",
        "TRADING_CALENDAR_REQUIRED": "Configure TRADING_CALENDAR_YEAR and TRADING_HOLIDAYS for the requested trading year. No price date was guessed.",
        "FUTURE_TRADE_DATE": "Choose today or an earlier date for historical closing prices.",
        "SUBSCRIPTION_CATEGORIES_NOT_CONFIGURED": "IPOAlerts does not supply Retail/QIB/NII subscriptions. Configure an approved category feed in MARKET_FEEDS_JSON or a verified BSE cumulative-demand mapping in BSE_IPO_ISSUES_JSON. NSE's issue list supplies totals only.",
        "NSE_SUBSCRIPTION_NOT_PUBLISHED": "NSE has not published a dated consolidated subscription snapshot for this symbol. Previous observations are retained; missing allocations are not zero subscriptions.",
        "NSE_SUBSCRIPTION_SCHEMA_CHANGED": "NSE consolidated category fields, timestamp or share-count validation failed. Review the retained raw payload before changing the mapping.",
        "IPOALERTS_PAGINATION_CHANGED": "IPOAlerts pagination changed or repeated records. The incomplete status batch was not published; rerun collection.",
        "IPOALERTS_TIME_BUDGET": "IPOAlerts collection reached the time budget. Completed status batches are retained; check plan limits and rerun.",
        "IPOALERTS_UNAVAILABLE": "IPOAlerts was unavailable after bounded retries. Previous published data is retained.",
        "EXCHANGE_HTTP_404": "The exchange URL or dated file was not found. Verify the official endpoint and trading date, then rerun the job.",
        "EXCHANGE_HTTP_403": "The exchange denied access. Verify permitted source access before retrying.",
        "BSE_ACCESS_REDIRECT": "BSE redirected the public IPO API to another page instead of returning data. Verify permitted API access with BSE; previous website data is retained.",
        "BSE_IPO_SCHEMA_CHANGED": "BSE did not return the expected Table list. Review the retained raw response and official field mapping.",
        "BSE_CROSS_EXCHANGE_MAPPING_REQUIRED": "A possible existing issuer was found. Add a verified shared ISIN or exchange identifier before retrying; no duplicate company was created.",
        "BSE_INVALID_IPO_ROW": "This BSE issue failed validation. Review the issue ID/name in Source / record and its retained raw payload.",
        "EXCHANGE_HTTP_406": "The exchange rejected this request. Review the source access requirements.",
        "ProgrammingError": "Database schema or query mismatch. Apply pending migrations and check worker diagnostics, then retry rejected records.",
        "BSE_IDENTIFIER_REQUIRED": "The earlier parser rejected a BSE-symbol issue. Update the connector and rerun IPO sync to collect it again.",
        "UNMAPPED_IDENTIFIER": "No company matches the source identifier. Import its IPO or correct the exchange mapping, then retry rejected records.",
        "INVALID_IPO_ROW": "The source IPO row failed validation. Review its retained raw payload and parser field mapping.",
        "NSE_IPO_SCHEMA_CHANGED": "The NSE response no longer matches the expected issue list. Review the retained raw response before updating the parser.",
        "TimeoutError": "The exchange request exceeded its time limit. Retry later; previous published data is retained.",
    }
    guidance.update(GUIDANCE)
    db.add(
        m.JobError(
            run_id=run.id,
            provider=provider,
            item=item[:200],
            code=code[:80],
            detail=guidance.get(
                code,
                "Collection/publication rejected; last published data retained. Review source mapping and raw payload.",
            ),
        )
    )


async def stage(db, kind, value, provider, authority, raw_id):
    config = FeedConfig(url="https://www.nseindia.com/", authority=authority)
    data = normalize_record(kind, value, config)
    if kind != "ipos":
        company = await match_company(db, data)
        # Subscriptions can refer to an IPO staged in this same collection run.
        if kind not in ("subscriptions", "gmp") and (not company or company.is_demo):
            return False
    payload = data.model_dump(mode="json")
    identity = {k: v for k, v in payload.items() if k != "source_timestamp"}
    if kind == "ipos":
        identity["issue"] = {k: v for k, v in payload["issue"].items() if k != "source_timestamp"}
    # Subscription observations retain a daily snapshot even when the multiple is unchanged.
    if kind in ("subscriptions", "gmp"):
        identity["day"] = (
            data.source_timestamp.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        )
    digest = fingerprint([kind, provider, identity])
    if await db.scalar(select(m.MarketStage.id).where(m.MarketStage.fingerprint == digest)):
        return False
    db.add(
        m.MarketStage(
            kind=kind,
            provider=provider,
            authority=authority,
            raw_payload_id=raw_id,
            fingerprint=digest,
            data=payload,
        )
    )
    await db.flush()
    return True


def record_context(kind, value):
    identifiers = [
        str(value[key])
        for key in ("bse_issue_id", "bse_symbol", "bse_code", "nse_symbol", "isin")
        if value.get(key)
    ]
    name = value.get("issue", {}).get("name", "")
    return ":".join([kind, *identifiers, name])[:200]


async def store_batch(db, run, provider, authority, url, raw, records, errors, counts):
    payload = await raw_payload(db, provider, records[0][0] if records else "collection", url, raw)
    counts["providers"] += 1
    for item, code in errors:
        error(db, run, provider, item, FeedError(code))
        counts["failed"] += 1
    for kind, value in records:
        counts["fetched"] += 1
        try:
            async with db.begin_nested():
                record_authority = (
                    "UNOFFICIAL"
                    if kind == "gmp"
                    else "BSE" if provider == "NSE" and value.get("bse_symbol") else authority
                )
                changed = await stage(db, kind, value, provider, record_authority, payload.id)
                counts["written" if changed else "unchanged"] += 1
        except Exception as exc:
            counts["failed"] += 1
            error(db, run, provider, record_context(kind, value), exc)


async def tracked_identifiers(db):
    companies = (
        await db.scalars(select(m.Company).join(m.IPO).where(m.Company.is_demo.is_(False)))
    ).all()
    ids = {
        "isin": {c.isin for c in companies if c.isin},
        "NSE": set(),
        "BSE": set(),
        "BSE_SYMBOL": set(),
    }
    for item in (
        await db.scalars(
            select(m.Identifier).where(m.Identifier.company_id.in_([c.id for c in companies]))
        )
    ).all():
        if item.exchange in ids:
            ids[item.exchange].add(item.ticker)
    return ids


def latest_trading_day(day, config):
    holidays = {value.strip() for value in config.trading_holidays.split(",") if value.strip()}
    if day > india_today():
        raise FeedError("FUTURE_TRADE_DATE")
    for _ in range(15):
        if day.year != config.trading_calendar_year:
            raise FeedError("TRADING_CALENDAR_REQUIRED")
        if day.weekday() < 5 and day.isoformat() not in holidays:
            return day
        day -= timedelta(days=1)
    raise FeedError("TRADING_DATE_NOT_FOUND")


async def collect(db, run, counts, download=ex.download):
    deadline = time.monotonic() + 170
    config, today = settings(), india_today()
    if (run.parameters or {}).get("trade_date"):
        today = date.fromisoformat(run.parameters["trade_date"])
    kinds = PIPELINE_JOBS[run.job_name][2]
    if "prices" in kinds:
        requested = today
        try:
            today = latest_trading_day(today, config)
        except FeedError as exc:
            error(db, run, "calendar", "prices", exc)
            counts["failed"] += 1
            return str(exc)
        run.parameters = {
            **(run.parameters or {}),
            "requested_date": requested.isoformat(),
            "resolved_trade_date": today.isoformat(),
        }
    if "ipos" in kinds and config.ipo_data_provider == "ipoalerts":
        from packages.providers.ipo import get_ipo_provider

        provider = get_ipo_provider(config)
        try:
            async for batch in provider.batches(deadline):
                await store_batch(
                    db,
                    run,
                    provider.name,
                    provider.authority,
                    batch.url,
                    batch.raw,
                    batch.records,
                    batch.errors,
                    counts,
                )
        except Exception as exc:
            counts["failed"] += 1
            error(db, run, provider.name, "ipos", exc)
    direct_ipos = config.ipo_data_provider == "exchange"
    if config.exchange_direct_enabled:
        requests = []
        if "ipos" in kinds and direct_ipos:
            requests = [("NSE", ex.NSE_IPO, False), ("NSE", ex.NSE_UPCOMING, True)]
        elif "subscriptions" in kinds and not config.nse_subscription_categories_enabled:
            # Catalogue ownership must not disable independent subscription observations.
            requests = [("NSE", ex.NSE_IPO, False)]
        elif "prices" in kinds:
            identities = await tracked_identifiers(db)
            if not any(identities.values()):
                return "NO_TRACKED_LISTED_COMPANIES"
            requests = [
                (exchange, ex.bhavcopy_url(exchange, today), False) for exchange in ("NSE", "BSE")
            ]
        for exchange, url, upcoming in requests:
            try:
                content = await download(url)
                parsed = (
                    ex.parse_nse_ipos(content, m.now(), upcoming)
                    if "ipos" in kinds
                    else ex.parse_bhavcopy(content, exchange, today, identities, m.now())
                )
                if "subscriptions" in kinds and not direct_ipos:
                    raw, records, errors = parsed
                    parsed = (
                        raw,
                        [(kind, value) for kind, value in records if kind == "subscriptions"],
                        errors,
                    )
                await store_batch(db, run, exchange, exchange, url, *parsed, counts)
            except Exception as exc:
                counts["failed"] += 1
                if isinstance(exc, FeedError) and exc.raw:
                    await raw_payload(db, exchange, kinds[0], url, exc.raw)
                error(db, run, exchange, url, exc)
        if "ipos" in kinds and direct_ipos:
            from packages.providers.bse_ipo import BSE_LIST_URL, parse_issues

            try:
                if time.monotonic() > deadline:
                    raise FeedError("COLLECTION_TIME_BUDGET_RETRY")
                parsed = parse_issues(await download(BSE_LIST_URL), m.now())
                await store_batch(db, run, "BSE", "BSE", BSE_LIST_URL, *parsed, counts)
            except Exception as exc:
                counts["failed"] += 1
                if isinstance(exc, FeedError) and exc.raw:
                    await raw_payload(db, "BSE", "ipos", BSE_LIST_URL, exc.raw)
                if isinstance(exc, FeedError) and str(exc) in {
                    "EXCHANGE_HTTP_301",
                    "EXCHANGE_HTTP_302",
                    "EXCHANGE_HTTP_307",
                    "EXCHANGE_HTTP_308",
                }:
                    exc = FeedError("BSE_ACCESS_REDIRECT")
                error(db, run, "BSE", "ipos:" + BSE_LIST_URL, exc)
        if "subscriptions" in kinds and config.nse_subscription_categories_enabled:
            await collect_nse_categories(db, run, counts, download, deadline)
        if "subscriptions" in kinds:
            from packages.providers.bse_ipo import BseIpoProvider
            from packages.providers.bse_ipo import configuration as bse_configuration

            for issue in bse_configuration(config.bse_ipo_issues_json):
                try:
                    if time.monotonic() > deadline:
                        raise FeedError("COLLECTION_TIME_BUDGET_RETRY")
                    company = await match_company(db, issue)
                    if not company or company.is_demo:
                        continue
                    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
                    if not ipo or ipo.status not in ("OPEN", "CLOSED"):
                        continue
                    parsed = await BseIpoProvider().fetch(issue, m.now(), download)
                    await store_batch(
                        db, run, "BSE", "BSE", BseIpoProvider.url(issue.issue_id), *parsed, counts
                    )
                except Exception as exc:
                    counts["failed"] += 1
                    if isinstance(exc, FeedError) and exc.raw:
                        await raw_payload(
                            db, "BSE", "subscriptions", BseIpoProvider.url(issue.issue_id), exc.raw
                        )
                    error(db, run, "BSE", "subscriptions", exc)
        for source in ex.discovery_sources(config.exchange_sources_json):
            if source.kind not in kinds or (source.kind == "ipos" and not direct_ipos):
                continue
            try:
                await collect_discovery(db, run, source, counts, download, deadline)
            except Exception as exc:
                counts["failed"] += 1
                error(db, run, source.name, source.kind, exc)
    # Existing approved feeds remain useful for unofficial GMP and optional provider mappings.
    for kind, providers in configuration(config.market_feeds_json).items():
        if kind not in kinds or (kind == "ipos" and config.ipo_data_provider == "ipoalerts"):
            continue
        for name, source in providers.items():
            if not source.enabled:
                continue
            try:
                if time.monotonic() > deadline:
                    raise FeedError("COLLECTION_TIME_BUDGET_RETRY")
                raw, records = await fetch_feed(
                    source,
                    {"from": (today - timedelta(days=14)).isoformat(), "to": today.isoformat()},
                )
                normalized, rejected = [], []
                for index, record in enumerate(records):
                    try:
                        normalized.append(
                            (kind, normalize_record(kind, record, source).model_dump(mode="json"))
                        )
                    except Exception as exc:
                        rejected.append(
                            (
                                f"{kind}:{index}",
                                str(exc) if isinstance(exc, FeedError) else "INVALID_RECORD",
                            )
                        )
                await store_batch(
                    db, run, name, source.authority, source.url, raw, normalized, rejected, counts
                )
            except Exception as exc:
                counts["failed"] += 1
                if isinstance(exc, FeedError) and exc.raw is not None:
                    await raw_payload(db, name, kind, source.url, exc.raw)
                error(db, run, name, kind, exc)
    if "subscriptions" in kinds and not (
        (config.exchange_direct_enabled and config.nse_subscription_categories_enabled)
        or any(
            feed.enabled
            for feed in configuration(config.market_feeds_json).get("subscriptions", {}).values()
        )
        or (
            config.exchange_direct_enabled
            and (
                json.loads(config.bse_ipo_issues_json or "[]")
                or any(
                    source.kind == "subscriptions"
                    for source in ex.discovery_sources(config.exchange_sources_json)
                )
            )
        )
    ):
        error(
            db,
            run,
            "configuration",
            "subscriptions:categories",
            FeedError("SUBSCRIPTION_CATEGORIES_NOT_CONFIGURED"),
        )
    return None if counts["providers"] or counts["failed"] else "SOURCE_CONFIGURATION_REQUIRED"


async def collect_nse_categories(db, run, counts, download, deadline):
    from packages.providers import nse_subscriptions as source

    today = india_today()
    targets = {}
    for (symbol,) in (
        await db.execute(
            select(m.Identifier.ticker)
            .join(m.Company, m.Company.id == m.Identifier.company_id)
            .join(m.IPO, m.IPO.company_id == m.Company.id)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .where(
                m.Identifier.exchange == "NSE",
                m.Company.is_demo.is_(False),
                m.IPODate.open_date <= today,
                m.IPODate.close_date >= today - timedelta(days=3),
            )
        )
    ).all():
        targets[symbol] = {"nse_symbol": symbol}
    # Also collect newly discovered issues before their staged master is published.
    for row in (
        await db.scalars(
            select(m.MarketStage).where(
                m.MarketStage.kind == "ipos", m.MarketStage.status == "PENDING"
            )
        )
    ).all():
        data = row.data
        symbol = data.get("nse_symbol")
        opened, closed = data["issue"].get("open_date"), data["issue"].get("close_date")
        if (
            symbol
            and opened
            and closed
            and date.fromisoformat(opened) <= today
            and date.fromisoformat(closed) >= today - timedelta(days=3)
        ):
            targets[symbol] = {"nse_symbol": symbol}
    for symbol, identity in sorted(targets.items()):
        try:
            if time.monotonic() >= deadline:
                raise FeedError("COLLECTION_TIME_BUDGET_RETRY")
            parsed = source.parse(await download(source.url(symbol)), symbol, identity)
            await store_batch(
                db, run, "NSE_CONSOLIDATED", "NSE", source.url(symbol), *parsed, counts
            )
        except Exception as exc:
            counts["failed"] += 1
            if isinstance(exc, FeedError) and exc.raw:
                await raw_payload(
                    db, "NSE_CONSOLIDATED", "subscriptions", source.url(symbol), exc.raw
                )
            error(db, run, "NSE_CONSOLIDATED", "subscriptions:" + symbol, exc)
            if time.monotonic() >= deadline:
                break


async def collect_discovery(db, run, source, counts, download, deadline):
    from packages.providers.market import Identity

    today = india_today()
    # Two-week overlap catches late submissions and a missed weekly run. Unchanged filings are skipped.
    fetched = 0
    for page in range(1, 6):
        if time.monotonic() > deadline:
            raise FeedError("COLLECTION_TIME_BUDGET_RETRY")
        url = ex.discovery_url(source, today - timedelta(days=14), today, page)
        content = await download(url)
        await raw_payload(db, source.name, source.kind, url, content.decode("utf-8-sig"))
        counts["providers"] += 1
        rows = ex.discovery_rows(content, source)
        for index, row in enumerate(rows):
            try:
                value = ex.mapped_row(row, source)
                if source.kind != "results":
                    # Native source mappings target the established validated IPO/subscription schema.
                    await store_batch(
                        db,
                        run,
                        source.name,
                        source.exchange,
                        url,
                        json.dumps(row),
                        [(source.kind, value)],
                        [],
                        counts,
                    )
                    continue
                identity = Identity.model_validate(
                    {key: value.get(key) for key in ("isin", "nse_symbol", "bse_code")}
                )
                company = await match_company(db, identity)
                if not company or company.is_demo:
                    continue
                filing_url = ex.exchange_url(value.pop("xbrl_url"))
                value["source_timestamp"] = ex.source_timestamp(
                    value["source_timestamp"]
                ).isoformat()
                value["filing_id"] = str(value.get("filing_id") or fingerprint(filing_url))
                if company.isin:
                    value["isin"] = company.isin
                # Revisions with a new filing ID or exchange broadcast timestamp are downloaded again.
                known = (
                    await db.scalars(
                        select(m.MarketStage).where(
                            m.MarketStage.provider == source.name, m.MarketStage.kind == "results"
                        )
                    )
                ).all()
                if any(
                    r.data.get("filing_id") == value.get("filing_id")
                    and ex.source_timestamp(r.data["source_timestamp"])
                    == ex.source_timestamp(value["source_timestamp"])
                    for r in known
                ):
                    continue
                if fetched >= 20 or time.monotonic() > deadline:
                    raise FeedError("FILING_BATCH_LIMIT_RETRY")
                xml = (await download(filing_url)).decode("utf-8-sig")
                fetched += 1
                payload = await raw_payload(db, source.name, "results-xbrl", filing_url, xml)
                value["source_url"] = filing_url
                records = ex.financial_records(xml, value, source.concepts)
                for record in records:
                    counts["fetched"] += 1
                    async with db.begin_nested():
                        changed = await stage(
                            db, "results", record, source.name, source.exchange, payload.id
                        )
                        counts["written" if changed else "unchanged"] += 1
            except Exception as exc:
                counts["failed"] += 1
                error(db, run, source.name, f"{source.kind}:{page}:{index}", exc)
                if isinstance(exc, FeedError) and str(exc) == "FILING_BATCH_LIMIT_RETRY":
                    return
        if not source.page_param or len(rows) < source.page_size:
            return
    raise FeedError("DISCOVERY_PAGE_LIMIT_REACHED")


async def publish(db, run, counts):
    kinds = PIPELINE_JOBS[run.job_name][2]
    states = (
        ["PENDING", "REJECTED"] if (run.parameters or {}).get("retry_rejected") else ["PENDING"]
    )
    rows = (
        await db.scalars(
            select(m.MarketStage)
            .where(m.MarketStage.status.in_(states), m.MarketStage.kind.in_(kinds))
            .order_by(m.MarketStage.created_at)
            .limit(1000)
        )
    ).all()
    # Create IPO masters before their subscriptions; prefer NSE before BSE for prices.
    rows.sort(key=lambda r: (kinds.index(r.kind), 0 if r.authority == "NSE" else 1, r.created_at))
    for row in rows:
        from packages.providers.ipo import primary_ipo_provider

        primary = primary_ipo_provider(settings())
        if row.kind == "ipos" and (
            (primary and row.provider != primary)
            or (settings().ipo_data_provider == "exchange" and row.provider == "IPOALERTS")
        ):
            row.status, row.published_at = "FALLBACK_NOT_NEEDED", m.now()
            counts["unchanged"] += 1
            continue
        counts["fetched"] += 1
        try:
            async with db.begin_nested():
                data = normalize_record(
                    row.kind,
                    row.data,
                    FeedConfig(url="https://www.nseindia.com/", authority=row.authority),
                )
                company = await match_company(db, data)
                if company and company.is_demo:
                    raise FeedError("DEMO_COMPANY_NOT_ALLOWED")
                if company and row.kind == "ipos":
                    existing_ipo = await db.scalar(
                        select(m.IPO).where(m.IPO.company_id == company.id)
                    )
                    if existing_ipo and existing_ipo.status == "LISTED":
                        data.issue.status, data.official_status = "LISTED", "LISTED"
                if row.kind == "prices" and company:
                    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
                    dates = (
                        await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
                        if ipo
                        else None
                    )
                    if not ipo:
                        raise FeedError("IPO_MAPPING_MISSING")
                    if ipo.status != "LISTED":
                        if not dates or not dates.close_date or data.price_date <= dates.close_date:
                            raise FeedError("LISTING_REQUIRES_REVIEW")
                        # An official traded close proves listing, but does not prove the initial listing date/price.
                        ipo.status = ipo.raw_status = ipo.lifecycle = "LISTED"
                    if data.isin and not company.isin:
                        company.isin = data.isin
                    history = await db.scalar(
                        select(m.ExchangePrice).where(
                            m.ExchangePrice.company_id == company.id,
                            m.ExchangePrice.price_date == data.price_date,
                            m.ExchangePrice.exchange == row.authority,
                        )
                    )
                    if not history:
                        history = m.ExchangePrice(
                            company_id=company.id,
                            price_date=data.price_date,
                            exchange=row.authority,
                        )
                        db.add(history)
                    history.data, history.raw_payload_id = row.data, row.raw_payload_id
                    existing = await db.scalar(
                        select(m.Price).where(
                            m.Price.company_id == company.id, m.Price.price_date == data.price_date
                        )
                    )
                    existing_authority = None
                    if existing:
                        existing_authority = (
                            await db.scalar(
                                select(m.MarketStage.authority)
                                .where(m.MarketStage.raw_payload_id == existing.raw_payload_id)
                                .limit(1)
                            )
                            if existing.raw_payload_id
                            else None
                        )
                        existing_authority = existing_authority or existing.source_provider
                    if existing and existing_authority == "NSE" and row.authority == "BSE":
                        row.status, row.published_at = "FALLBACK_NOT_NEEDED", m.now()
                        counts["unchanged"] += 1
                        continue
                    if existing and row.authority == "NSE" and existing_authority == "BSE":
                        # Canonical daily close is NSE; the BSE observation remains in staging/raw history.
                        existing.source_provider, existing.source_timestamp = row.provider, None
                changed = await ingest_record(
                    db, row.kind, data, row.provider, row.authority, row.raw_payload_id
                )
                row.status, row.published_at, row.error = "PUBLISHED", m.now(), None
                counts["written" if changed else "unchanged"] += 1
        except Exception as exc:
            row.status, row.error = (
                "REJECTED",
                (str(exc)[:100] if isinstance(exc, FeedError) else type(exc).__name__),
            )
            counts["failed"] += 1
            error(db, run, row.provider, record_context(row.kind, row.data), exc)
    await reconcile_lifecycle(db, india_today())
    counts["providers"] = 1 if rows else 0
    return None if rows else "NO_PENDING_RECORDS"


async def run_pipeline(db, run, download=None):
    base_job = (
        "sync-" + EXCHANGE_JOBS[run.job_name][1] if run.job_name in EXCHANGE_JOBS else run.job_name
    )
    run.parameters = job_parameters(run.job_name, run.parameters)
    if download is None:
        if base_job == "sync-prices":
            from packages.providers.bhavcopy import download
        else:
            download = ex.download
    if run.status != "QUEUED":
        return run
    if run.job_name in SCHEDULED_JOBS:
        earlier = await db.scalar(
            select(m.ImportRun.id)
            .where(
                m.ImportRun.job_name.in_(SCHEDULED_JOBS),
                m.ImportRun.status == "QUEUED",
                or_(
                    m.ImportRun.created_at < run.created_at,
                    and_(m.ImportRun.created_at == run.created_at, m.ImportRun.id < run.id),
                ),
            )
            .order_by(m.ImportRun.created_at, m.ImportRun.id)
            .limit(1)
        )
        if earlier:
            run.error, run.updated_at = f"WAITING_FOR_PREVIOUS_JOB: {earlier}", m.now()
            await db.commit()
            return run
    if not await acquire(db, run.id):
        if run.job_name in SCHEDULED_JOBS:
            run.error, run.updated_at = "WAITING_FOR_PREVIOUS_JOB: active data import", m.now()
            await db.commit()
            return run
        run.status, run.error, run.finished_at = "SKIPPED", "Another market job is running", m.now()
        await db.commit()
        return run
    claimed = await db.execute(
        update(m.ImportRun)
        .where(m.ImportRun.id == run.id, m.ImportRun.status == "QUEUED")
        .values(status="RUNNING", started_at=m.now(), error=None)
    )
    if not claimed.rowcount:
        await db.execute(delete(m.JobLock).where(m.JobLock.owner == run.id))
        await db.commit()
        await db.refresh(run)
        return run
    await db.refresh(run)
    await db.commit()
    run_id = run.id
    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    try:
        control = await db.get(m.SchedulerControl, run.job_name)
        paused = bool(control and control.paused)
        if run.job_name in SCHEDULED_JOBS:
            from packages.shared.job_schedules import schedule_state

            paused = (await schedule_state(db, run.job_name, settings()))["paused"]
        if paused:
            note = "PAUSED"
        elif base_job == "sync-prices":
            from apps.worker.bhavcopy import sync

            note = await sync(db, run, counts, download=download)
        elif base_job == "sync-results" and (
            run.job_name in EXCHANGE_JOBS
            or (
                not any(
                    source.kind == "results"
                    for source in ex.discovery_sources(settings().exchange_sources_json)
                )
                and not configuration(settings().market_feeds_json).get("results")
            )
        ):
            from apps.worker.results import sync

            note = await sync(db, run, counts)
        elif run.job_name.startswith("sync-"):
            note = await collect(db, run, counts, download)
            # Durable staging survives a later publishing failure; the same worker retains the lease.
            await db.commit()
            publication = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
            publish_note = await publish(db, run, publication)
            counts["staged"] = counts["written"]
            counts["written"] = publication["written"]
            counts["failed"] += publication["failed"]
            counts["unchanged"] += publication["unchanged"]
            counts["providers"] = counts["providers"] or publication["providers"]
            note = note or publish_note
        else:
            note = (
                await collect(db, run, counts, download)
                if run.job_name.startswith("collect-")
                else await publish(db, run, counts)
            )
        run.status = (
            ("PARTIAL" if counts["providers"] else "FAILED")
            if counts["failed"]
            else "SUCCESS" if counts["providers"] else "SKIPPED"
        )
        await db.flush()
        last_error = await db.scalar(
            select(m.JobError)
            .where(m.JobError.run_id == run.id)
            .order_by(m.JobError.created_at.desc())
            .limit(1)
        )
        run.error = note or (last_error.code if last_error else None)
    except Exception as exc:
        await db.rollback()
        run = await db.get(m.ImportRun, run_id)
        run.status, run.error = (
            "FAILED",
            "Pipeline failed; check source configuration and worker logs",
        )
        counts["written"] = 0
        counts["failed"] += 1
        error(db, run, "pipeline", run.job_name, exc)
    run.counters, run.finished_at = counts, m.now()
    await db.execute(delete(m.JobLock).where(m.JobLock.owner == run.id))
    from apps.api.cache import commit_with_invalidation

    await commit_with_invalidation(db)
    return run

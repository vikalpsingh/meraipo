"""Collect into staging; publish separately under the shared database writer lease."""

import json
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

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

PIPELINE_JOBS = {
    "sync-ipos": ("IPO, subscription & GMP sync", "23:00 daily", ["ipos", "subscriptions", "gmp"]),
    "sync-prices": ("Daily closing price sync", "23:10 trading days", ["prices"]),
    "sync-results": ("Quarterly result sync", "21:00 Friday", ["results"]),
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
    code = str(exc) if isinstance(exc, FeedError) else type(exc).__name__
    db.add(
        m.JobError(
            run_id=run.id,
            provider=provider,
            item=item[:200],
            code=code[:80],
            detail="Collection/publication rejected; last published data retained. Review source mapping and raw payload.",
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
    if kind == "subscriptions":
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
                changed = await stage(db, kind, value, provider, authority, payload.id)
                counts["written" if changed else "unchanged"] += 1
        except Exception as exc:
            counts["failed"] += 1
            error(db, run, provider, kind, exc)


async def tracked_identifiers(db):
    companies = (
        await db.scalars(select(m.Company).join(m.IPO).where(m.Company.is_demo.is_(False)))
    ).all()
    ids = {"isin": {c.isin for c in companies if c.isin}, "NSE": set(), "BSE": set()}
    for item in (
        await db.scalars(
            select(m.Identifier).where(m.Identifier.company_id.in_([c.id for c in companies]))
        )
    ).all():
        if item.exchange in ids:
            ids[item.exchange].add(item.ticker)
    return ids


async def collect(db, run, counts, download=ex.download):
    deadline = time.monotonic() + 170
    config, today = settings(), india_today()
    kinds = PIPELINE_JOBS[run.job_name][2]
    if "prices" in kinds and (
        today.weekday() >= 5 or today.isoformat() in config.trading_holidays.split(",")
    ):
        return "NOT_A_TRADING_DAY"
    if "prices" in kinds and config.trading_calendar_year != today.year:
        return "TRADING_CALENDAR_REQUIRED"
    if config.exchange_direct_enabled:
        requests = []
        if "ipos" in kinds:
            requests = [("NSE", ex.NSE_IPO, False), ("NSE", ex.NSE_UPCOMING, True)]
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
                await store_batch(db, run, exchange, exchange, url, *parsed, counts)
            except Exception as exc:
                counts["failed"] += 1
                if isinstance(exc, FeedError) and exc.raw:
                    await raw_payload(db, exchange, kinds[0], url, exc.raw)
                error(db, run, exchange, kinds[0], exc)
        for source in ex.discovery_sources(config.exchange_sources_json):
            if source.kind not in kinds:
                continue
            try:
                await collect_discovery(db, run, source, counts, download, deadline)
            except Exception as exc:
                counts["failed"] += 1
                error(db, run, source.name, source.kind, exc)
    # Existing approved feeds remain useful for unofficial GMP and optional provider mappings.
    for kind, providers in configuration(config.market_feeds_json).items():
        if kind not in kinds:
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
    return None if counts["providers"] or counts["failed"] else "SOURCE_CONFIGURATION_REQUIRED"


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
            row.status, row.error = "REJECTED", (
                str(exc)[:100] if isinstance(exc, FeedError) else type(exc).__name__
            )
            counts["failed"] += 1
            error(db, run, row.provider, row.kind, exc)
    await reconcile_lifecycle(db, india_today())
    counts["providers"] = 1 if rows else 0
    return None if rows else "NO_PENDING_RECORDS"


async def run_pipeline(db, run, download=ex.download):
    if run.status != "QUEUED":
        return run
    if not await acquire(db, run.id):
        run.status, run.error, run.finished_at = "SKIPPED", "Another market job is running", m.now()
        await db.commit()
        return run
    run.status, run.started_at = "RUNNING", m.now()
    await db.commit()
    run_id = run.id
    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    try:
        control = await db.get(m.SchedulerControl, run.job_name)
        if control and control.paused:
            note = "PAUSED"
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
        run.error = note
    except Exception as exc:
        await db.rollback()
        run = await db.get(m.ImportRun, run_id)
        run.status, run.error = (
            "FAILED",
            "Pipeline failed; check source configuration and worker logs",
        )
        counts["written"] = 0
        error(db, run, "pipeline", run.job_name, exc)
    run.counters, run.finished_at = counts, m.now()
    await db.execute(delete(m.JobLock).where(m.JobLock.owner == run.id))
    from apps.api.cache import commit_with_invalidation

    await commit_with_invalidation(db)
    return run

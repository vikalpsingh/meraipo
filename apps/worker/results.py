"""Daily result discovery and attachment processing under the existing writer lease."""

import asyncio
import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import select

from packages.database import models as m
from packages.providers import results as feed
from packages.shared.calculations import utc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def company_identifiers(db, company):
    values = {"ISIN": {company.isin} if company.isin else set(), "BSE": set(), "NSE": set()}
    for row in (
        await db.scalars(select(m.Identifier).where(m.Identifier.company_id == company.id))
    ).all():
        if row.exchange in values:
            values[row.exchange].add(row.ticker)
    return values


async def refresh_bse_identifiers(db):
    """Reuse exact-identifier matches already validated by the bhavcopy importer."""
    rows = (
        await db.scalars(
            select(m.DailyClose)
            .where(m.DailyClose.exchange == "BSE")
            .order_by(m.DailyClose.trade_date.desc())
        )
    ).all()
    for close in rows:
        company = await db.get(m.Company, close.company_id)
        if company.is_demo or (company.isin and company.isin != close.isin):
            continue
        existing = await db.scalar(
            select(m.Identifier).where(
                m.Identifier.exchange == "BSE", m.Identifier.ticker == close.security_id
            )
        )
        if existing:
            continue
        db.add(m.Identifier(company_id=company.id, exchange="BSE", ticker=close.security_id))
        await db.flush()


async def store_filing(db, exchange, metadata):
    identifier = str(metadata["identifier"]).strip()
    mapping = await db.scalar(
        select(m.Identifier).where(
            m.Identifier.exchange == exchange, m.Identifier.ticker == identifier
        )
    )
    identity = digest([exchange, metadata])
    existing = await db.scalar(select(m.ResultFiling).where(m.ResultFiling.identity == identity))
    if existing:
        return existing, False
    row = m.ResultFiling(
        exchange=exchange,
        identity=identity,
        identifier=identifier,
        company_id=mapping.company_id if mapping else None,
        metadata_json=metadata,
        announced_at=(
            feed.source_timestamp(metadata["announced_at"])
            if metadata.get("announced_at")
            else None
        ),
        status="AWAITING_PROCESSING" if mapping else "UNRESOLVED_MAPPING",
    )
    db.add(row)
    await db.flush()
    return row, True


async def publish(db, filing, parsed):
    if not filing.announced_at:
        raise feed.SourceError("FILING_TIMESTAMP_REVIEW_REQUIRED")
    published = 0
    for item in parsed:
        query = select(m.FinancialResult).where(
            m.FinancialResult.company_id == filing.company_id,
            m.FinancialResult.period_start == date.fromisoformat(item["period_start"]),
            m.FinancialResult.period_end == date.fromisoformat(item["period_end"]),
            m.FinancialResult.period_type == item["period_type"],
            m.FinancialResult.basis == item["basis"],
            m.FinancialResult.current.is_(True),
        )
        current = await db.scalar(query)
        if current:
            if current.facts == item["facts"]:
                current.provenance = sorted(set(current.provenance + [filing.id]))
                continue
            previous = await db.get(m.ResultFiling, current.filing_id)
            if previous.exchange != filing.exchange:
                raise feed.SourceError("CROSS_EXCHANGE_CONFLICT")
            if utc(previous.announced_at) >= utc(filing.announced_at):
                raise feed.SourceError("OLDER_OR_CONFLICTING_REVISION")
            current.current = False
        db.add(
            m.FinancialResult(
                company_id=filing.company_id,
                filing_id=filing.id,
                period_start=date.fromisoformat(item["period_start"]),
                period_end=date.fromisoformat(item["period_end"]),
                period_type=item["period_type"],
                basis=item["basis"],
                revision=current.revision + 1 if current else 1,
                current=True,
                facts=item["facts"],
                provenance=[filing.id],
            )
        )
        published += 1
    await db.flush()
    filing.status, filing.error = "PUBLISHED", None
    return published


async def store_attachment(db, filing, content, url):
    mime = feed.attachment_type(content)
    checksum = hashlib.sha256(content).hexdigest()
    row = await db.scalar(
        select(m.ResultAttachment).where(
            m.ResultAttachment.filing_id == filing.id, m.ResultAttachment.checksum == checksum
        )
    )
    if not row:
        row = m.ResultAttachment(
            filing_id=filing.id,
            source_url=url,
            checksum=checksum,
            content_type=mime,
            content=content,
            parser_version=feed.VERSION,
        )
        db.add(row)
        await db.flush()
    return row


async def preview(db, filing, content):
    company = await db.get(m.Company, filing.company_id) if filing.company_id else None
    if not company:
        raise feed.SourceError("UNRESOLVED_MAPPING")
    if company.company_type in ("BANK", "NBFC", "INSURANCE"):
        raise feed.SourceError("SECTOR_TEMPLATE_REVIEW_REQUIRED")
    return feed.parse_xbrl(
        content,
        await company_identifiers(db, company),
        filing.metadata_json.get("basis"),
        filing.metadata_json.get("period_end"),
    )


async def process(db, filing, session, counts):
    urls = filing.metadata_json.get("attachments", [])
    if not urls:
        filing.status, filing.error = (
            "PARSING_REVIEW_REQUIRED",
            "Original result attachment link required; reporting codes are not period IDs.",
        )
        return
    filing.attempts += 1
    parsed_any = False
    for url in urls:
        try:
            existing = await db.scalar(
                select(m.ResultAttachment).where(
                    m.ResultAttachment.filing_id == filing.id, m.ResultAttachment.source_url == url
                )
            )
            content = existing.content if existing else await session.get(url)
            attachment = existing or await store_attachment(db, filing, content, url)
            counts["downloaded"] += int(existing is None)
            # Persist the original even if its metrics need review.
            await db.commit()
            if attachment.content_type != "application/xml":
                continue
            parsed = await preview(db, filing, content)
            async with db.begin_nested():
                counts["published"] += await publish(db, filing, parsed)
            counts["parsed"] += 1
            parsed_any = True
        except Exception as exc:
            filing.error = str(exc) if isinstance(exc, feed.FeedError) else type(exc).__name__
            filing.status = (
                "DOWNLOAD_RETRY"
                if str(filing.error).startswith("SOURCE_")
                else "PARSING_REVIEW_REQUIRED"
            )
            filing.retry_at = getattr(exc, "retry_at", None) or m.now() + timedelta(
                hours=min(24, 2 ** min(filing.attempts, 4))
            )
            counts["failed"] += 1
            break
    if not parsed_any and filing.status == "AWAITING_PROCESSING":
        filing.status = "PARSING_REVIEW_REQUIRED"
    await db.commit()


async def sync(db, run, counts, session_factory=feed.ExchangeSession):
    from apps.worker.exchange_pipeline import error
    from apps.worker.market import india_today

    for name in (
        "discovered",
        "matched",
        "downloaded",
        "parsed",
        "published",
        "skipped",
        "unresolved",
    ):
        counts.setdefault(name, 0)
    await refresh_bse_identifiers(db)
    parameters = run.parameters or {}
    today = india_today()
    end = date.fromisoformat(parameters.get("to", today.isoformat()))
    start = date.fromisoformat(parameters.get("from", (end - timedelta(days=13)).isoformat()))
    for exchange in parameters.get("exchanges", ["BSE", "NSE"]):
        state = await db.get(m.ResultSource, exchange)
        if not state:
            state = m.ResultSource(
                exchange=exchange, enabled=True, schedule="19:30", status="NOT_YET_RUN"
            )
            db.add(state)
            await db.flush()
        if not state.enabled:
            continue
        if state.retry_at and utc(state.retry_at) > m.now():
            counts["failed"] += 1
            error(
                db,
                run,
                exchange,
                "financial-results discovery",
                feed.FeedError("SOURCE_RATE_LIMITED"),
            )
            continue
        mappings = (
            await db.scalars(
                select(m.Identifier)
                .join(m.Company)
                .where(m.Identifier.exchange == exchange, m.Company.is_demo.is_(False))
            )
        ).all()
        if parameters.get("company_id"):
            mappings = [r for r in mappings if r.company_id == parameters["company_id"]]
        tracked = {r.ticker for r in mappings}
        if not tracked:
            continue
        if run.trigger == "reconciliation" and state.status == "SOURCE_ACCESS_BLOCKED":
            # A weekly batch must not repeat a known denial for every company.
            # The next daily/manual discovery can test whether access is restored.
            counts["failed"] += 1
            error(db, run, exchange, "financial-results history", feed.FeedError(state.status))
            await db.commit()
            continue
        try:
            async with asyncio.timeout(70), session_factory(exchange) as session:
                await session.initialize()
                history = bool(parameters.get("history"))
                if exchange == "NSE":
                    symbol = (
                        mappings[0].ticker if parameters.get("company_id") and mappings else None
                    )
                    rows = await feed.discover_nse(session, start, end, symbol)
                else:
                    rows = feed.bse_csv(await session.get(feed.BSE_TODAY))
                    codes = (
                        tracked
                        if history or parameters.get("company_id") or start != end
                        else {r["identifier"] for r in rows} & tracked
                    )
                    for code in sorted(codes):
                        rows.extend(await feed.discover_bse_history(session, code))
                counts["discovered"] += len(rows)
                for metadata in rows:
                    if metadata["identifier"] not in tracked:
                        counts["skipped"] += 1
                        continue
                    filing, created = await store_filing(db, exchange, metadata)
                    counts["matched"] += 1
                    counts["fetched"] += 1
                    counts["unchanged"] += int(not created)
                state.status, state.last_success, state.retry_at = "SUCCESS", m.now(), None
                if history and parameters.get("company_id"):
                    key = {"company_id": parameters["company_id"], "exchange": exchange}
                    checkpoint = await db.get(m.ResultHistory, key)
                    if not checkpoint:
                        checkpoint = m.ResultHistory(**key)
                        db.add(checkpoint)
                    checkpoint.completed_at, checkpoint.from_date, checkpoint.to_date = (
                        m.now(),
                        start,
                        end,
                    )
                    await db.flush()
                    required = set(
                        (
                            await db.scalars(
                                select(m.Identifier.company_id)
                                .join(m.Company)
                                .join(m.IPO)
                                .where(
                                    m.Identifier.exchange == exchange,
                                    m.Company.is_demo.is_(False),
                                    m.IPO.status == "LISTED",
                                )
                            )
                        ).all()
                    )
                    completed = set(
                        (
                            await db.scalars(
                                select(m.ResultHistory.company_id).where(
                                    m.ResultHistory.exchange == exchange,
                                    m.ResultHistory.completed_at >= m.now() - timedelta(days=7),
                                )
                            )
                        ).all()
                    )
                    if required <= completed:
                        state.reconciled_at = m.now()
                counts["providers"] += 1
                await db.commit()
        except Exception as exc:
            state.status = str(exc) if isinstance(exc, feed.FeedError) else "SOURCE_UNAVAILABLE"
            state.retry_at = getattr(exc, "retry_at", None)
            counts["failed"] += 1
            error(db, run, exchange, "financial-results discovery", feed.FeedError(state.status))
            await db.commit()
        # Retry attachments independently even when today's discovery fails.
        pending = (
            await db.scalars(
                select(m.ResultFiling)
                .where(
                    m.ResultFiling.exchange == exchange,
                    m.ResultFiling.company_id.is_not(None),
                    m.ResultFiling.status.in_(["AWAITING_PROCESSING", "DOWNLOAD_RETRY"]),
                )
                .order_by(m.ResultFiling.created_at)
                .limit(15)
            )
        ).all()
        try:
            async with asyncio.timeout(35), session_factory(exchange) as session:
                for filing in pending:
                    if filing.retry_at and utc(filing.retry_at) > m.now():
                        continue
                    await process(db, filing, session, counts)
        except TimeoutError:
            counts["failed"] += 1
    counts["written"] = counts["published"]
    return None


async def public_results(db, company_id):
    rows = (
        await db.scalars(
            select(m.FinancialResult)
            .where(m.FinancialResult.company_id == company_id, m.FinancialResult.current.is_(True))
            .order_by(m.FinancialResult.period_end.desc())
        )
    ).all()
    output = []
    for row in rows:
        filing = await db.get(m.ResultFiling, row.filing_id)
        output.append(
            {
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "period_type": row.period_type,
                "basis": row.basis,
                "revision": row.revision,
                "facts": row.facts,
                "exchange": filing.exchange,
                "filing_date": filing.announced_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "source_url": (
                    filing.metadata_json.get("attachments") or [filing.metadata_json["source_url"]]
                )[0],
            }
        )
    pending = await db.scalar(
        select(m.ResultFiling.id)
        .where(m.ResultFiling.company_id == company_id, m.ResultFiling.status != "PUBLISHED")
        .limit(1)
    )
    identifiers = (
        await db.scalars(select(m.Identifier.exchange).where(m.Identifier.company_id == company_id))
    ).all()
    exchanges = {"BSE" if value.startswith("BSE") else value for value in identifiers}
    sources = (
        await db.scalars(select(m.ResultSource).where(m.ResultSource.exchange.in_(exchanges)))
    ).all()
    return {
        "items": output,
        "status": (
            "AVAILABLE"
            if output
            else (
                "AWAITING_PROCESSING"
                if pending
                else (
                    "SOURCE_TEMPORARILY_UNAVAILABLE"
                    if any(s.status not in ("SUCCESS", "NOT_YET_RUN") for s in sources)
                    else "NOT_YET_REPORTED"
                )
            )
        ),
    }

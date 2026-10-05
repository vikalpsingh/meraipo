"""Shared daily-close service for the existing worker, upload preview and CLI."""

import hashlib
import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from packages.database import models as m
from packages.providers import bhavcopy as feed
from packages.providers.market import FeedError
from packages.shared.calculations import utc
from packages.shared.config import settings


def root():
    directory = Path(settings().bhavcopy_storage_path).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def managed_path(name):
    candidate = root() / name
    path = candidate.resolve()
    if path.parent != root() or candidate.is_symlink():
        raise FeedError("UNSAFE_STORAGE_PATH")
    return path


async def cleanup(db):
    """Expire original artifacts by retrieval age, never delete historical prices."""
    cutoff = m.now() - timedelta(days=7)
    files = (
        await db.scalars(
            select(m.BhavcopyFile).where(
                m.BhavcopyFile.created_at < cutoff,
                m.BhavcopyFile.path.is_not(None),
                m.BhavcopyFile.purged_at.is_(None),
            )
        )
    ).all()
    for item in files:
        managed_path(item.path).unlink(missing_ok=True)
        item.purged_at = m.now()
    # Only generated temporary files, in this directory, are eligible for orphan cleanup.
    for path in root().glob("*.tmp"):
        if not path.is_symlink() and path.stat().st_mtime < cutoff.timestamp():
            managed_path(path.name).unlink(missing_ok=True)
    await db.flush()
    return len(files)


def save_original(content, exchange, day, checksum):
    name = f"{exchange}-{day}-{checksum}-{uuid4().hex}{'.zip' if content.startswith(b'PK') else '.csv'}"
    destination = managed_path(name)
    temporary = managed_path(f"{uuid4()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return name


async def mappings(db, exchange):
    companies = (
        await db.scalars(
            select(m.Company)
            .join(m.IPO)
            .where(m.IPO.status == "LISTED", m.Company.is_demo.is_(False))
        )
    ).all()
    by_isin, by_id = defaultdict(set), defaultdict(set)
    for company in companies:
        if company.isin:
            by_isin[company.isin].add(company.id)
    if companies:
        identifiers = (
            await db.scalars(
                select(m.Identifier).where(
                    m.Identifier.company_id.in_([c.id for c in companies]),
                    m.Identifier.exchange.in_(
                        [exchange, "BSE_SYMBOL"] if exchange == "BSE" else [exchange]
                    ),
                )
            )
        ).all()
        for item in identifiers:
            by_id[(item.exchange, item.ticker)].add(item.company_id)
    return by_isin, by_id, {c.id: c for c in companies}


async def preview(db, content, exchange, day, parsed=None):
    rows, errors, total = parsed if parsed is not None else feed.parse(content, exchange, day)
    by_isin, by_id, companies = await mappings(db, exchange)
    matched, unmatched = [], 0
    for row in rows:
        candidates = (
            by_isin[row["isin"]]
            | by_id[(exchange, row["symbol"] if exchange == "NSE" else row["security_id"])]
        )
        if exchange == "BSE":
            candidates |= by_id[("BSE_SYMBOL", row["symbol"])]
        if not candidates:
            unmatched += 1
            continue
        if len(candidates) != 1:
            errors.append({"line": row["line"], "isin": row["isin"], "code": "IDENTIFIER_CONFLICT"})
            continue
        company_id = next(iter(candidates))
        if companies[company_id].isin and companies[company_id].isin != row["isin"]:
            errors.append({"line": row["line"], "isin": row["isin"], "code": "ISIN_CONFLICT"})
            continue
        matched.append({**row, "company_id": company_id})
    frequency = Counter(r["company_id"] for r in matched)
    repeated = {key for key, count in frequency.items() if count > 1}
    for row in matched:
        if row["company_id"] in repeated:
            errors.append(
                {"line": row["line"], "isin": row["isin"], "code": "AMBIGUOUS_COMPANY_ROWS"}
            )
    matched = [r for r in matched if r["company_id"] not in repeated]
    return (
        matched,
        errors,
        {
            "rows": total,
            "matched": len(matched),
            "unmatched": unmatched,
            "rejected": len(errors),
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
        },
    )


async def refresh_listing_prices(db):
    """Reconcile exact listing dates, including corrected dates and backfilled closes.

    Use the same exchange as CMP so returns never mix exchange price series.
    DailyClose revisions retain provenance when an exchange corrects its file.
    """
    rows = (
        await db.execute(
            select(m.Company, m.IPODate.listing_date, m.PriceSnapshot.closing_exchange)
            .join(m.IPO, m.IPO.company_id == m.Company.id)
            .outerjoin(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .outerjoin(m.PriceSnapshot, m.PriceSnapshot.company_id == m.Company.id)
            .where(m.Company.is_demo.is_(False))
        )
    ).all()
    closes = (
        await db.scalars(
            select(m.DailyClose)
            .join(m.IPO, m.IPO.company_id == m.DailyClose.company_id)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .where(m.DailyClose.trade_date == m.IPODate.listing_date)
        )
    ).all()
    prices = {(p.company_id, p.exchange, p.trade_date): p.close for p in closes}
    populated = 0
    for company, day, exchange in rows:
        value = prices.get((company.id, exchange, day))
        company.listing_price = value
        company.listing_price_date = day if value is not None else None
        company.listing_price_exchange = exchange if value is not None else None
        populated += value is not None
    await db.flush()
    return populated


async def refresh_summary(db, company_id, exchange):
    snapshot = await db.scalar(
        select(m.PriceSnapshot).where(m.PriceSnapshot.company_id == company_id)
    )
    if not snapshot:
        snapshot = m.PriceSnapshot(company_id=company_id)
        db.add(snapshot)
    # Once selected, a chart stays on one exchange even when the other file arrives later.
    if snapshot.closing_exchange and snapshot.closing_exchange != exchange:
        return
    snapshot.closing_exchange = exchange
    base = select(m.DailyClose).where(
        m.DailyClose.company_id == company_id, m.DailyClose.exchange == exchange
    )
    latest = await db.scalar(base.order_by(m.DailyClose.trade_date.desc()).limit(1))
    snapshot.cmp, snapshot.price_date, snapshot.previous_close = (
        latest.close,
        latest.trade_date,
        latest.previous_close,
    )
    high = func.coalesce(m.DailyClose.high, m.DailyClose.close)
    low = func.coalesce(m.DailyClose.low, m.DailyClose.close)
    criteria = (m.DailyClose.company_id == company_id, m.DailyClose.exchange == exchange)
    snapshot.ath = await db.scalar(select(func.max(high)).where(*criteria))
    snapshot.high_52w, snapshot.low_52w = (
        await db.execute(
            select(func.max(high), func.min(low)).where(
                *criteria, m.DailyClose.trade_date >= latest.trade_date - timedelta(days=365)
            )
        )
    ).one()


async def import_file(db, artifact, content, parsed=None):
    rows, errors, counters = await preview(
        db, content, artifact.exchange, artifact.trade_date, parsed
    )
    existing = (
        await db.scalars(
            select(m.DailyClose).where(
                m.DailyClose.exchange == artifact.exchange,
                m.DailyClose.trade_date == artifact.trade_date,
            )
        )
    ).all()
    by_company = {r.company_id: r for r in existing}
    affected = set()
    for row in rows:
        values = {key: row[key] for key in (*feed.PRICE_FIELDS, "security_id", "isin", "series")}
        price = by_company.get(row["company_id"])
        if price and all(getattr(price, key) == value for key, value in values.items()):
            counters["unchanged"] += 1
            continue
        if price:
            # All prior versions remain queryable after original files expire.
            db.add(
                m.DailyCloseRevision(
                    close_id=price.id,
                    file_id=price.file_id,
                    values={
                        key: str(getattr(price, key)) if getattr(price, key) is not None else None
                        for key in values
                    },
                )
            )
            counters["updated"] += 1
        else:
            price = m.DailyClose(
                company_id=row["company_id"],
                exchange=artifact.exchange,
                trade_date=artifact.trade_date,
            )
            db.add(price)
            counters["inserted"] += 1
        for key, value in values.items():
            setattr(price, key, value)
        price.file_id = artifact.id
        affected.add(row["company_id"])
    await db.flush()
    for company_id in affected:
        await refresh_summary(db, company_id, artifact.exchange)
    await refresh_listing_prices(db)
    artifact.counters, artifact.errors = counters, errors
    artifact.status = "PARTIAL" if errors else "SUCCESS"
    artifact.imported_at = m.now()
    return counters


async def process_source(db, run, exchange, day, *, download=feed.download, upload=None):
    source = feed.sources(settings().bhavcopy_sources_json)[exchange]
    artifact = m.BhavcopyFile(
        run_id=run.id,
        exchange=exchange,
        trade_date=day,
        source_url="manual-upload" if upload else "",
        status="STARTED",
    )
    db.add(artifact)
    await db.flush()
    try:
        if upload:
            saved = await db.get(m.BhavcopyFile, upload)
            if (
                not saved
                or saved.exchange != exchange
                or saved.trade_date != day
                or saved.purged_at
            ):
                raise FeedError("UPLOAD_NOT_AVAILABLE")
            content = managed_path(saved.path).read_bytes()
            if hashlib.sha256(content).hexdigest() != saved.checksum:
                raise FeedError("UPLOAD_CHECKSUM_MISMATCH")
            artifact.source_url = saved.source_url
        else:
            if not source.enabled:
                artifact.status = "DISABLED"
                return artifact
            artifact.source_url = feed.source_url(exchange, day, source)
            retry_at = await db.scalar(
                select(func.max(m.BhavcopyFile.retry_at)).where(m.BhavcopyFile.exchange == exchange)
            )
            if retry_at and utc(retry_at) > m.now():
                artifact.status, artifact.retry_at = "RATE_LIMITED_RETRY_LATER", retry_at
                return artifact
            if not feed.trading_session(day, source):
                artifact.status = "NOT_A_TRADING_SESSION"
                return artifact
            if run.trigger == "scheduled" and await db.scalar(
                select(m.BhavcopyFile.id).where(
                    m.BhavcopyFile.exchange == exchange,
                    m.BhavcopyFile.trade_date == day,
                    m.BhavcopyFile.error == "SOURCE_ACCESS_BLOCKED",
                )
            ):
                artifact.status = "BLOCKED_ADMIN_REQUIRED"
                return artifact
            if run.trigger == "scheduled" and await db.scalar(
                select(m.BhavcopyFile.id).where(
                    m.BhavcopyFile.exchange == exchange,
                    m.BhavcopyFile.trade_date == day,
                    m.BhavcopyFile.status.in_(["SUCCESS", "PARTIAL"]),
                    m.BhavcopyFile.imported_at.is_not(None),
                )
            ):
                artifact.status = "ALREADY_IMPORTED"
                return artifact
            content = await download(artifact.source_url)
        # Validation precedes the atomic rename. Never store HTML as an exchange archive.
        artifact.checksum = hashlib.sha256(content).hexdigest()
        parsed = feed.parse(content, exchange, day)
        artifact.path = save_original(content, exchange, day, artifact.checksum)
        async with db.begin_nested():
            await import_file(db, artifact, content, parsed)
    except Exception as exc:
        artifact.status = "FAILED"
        if isinstance(exc, feed.RateLimited):
            artifact.retry_at = exc.retry_at
        artifact.error = str(exc)[:200] if isinstance(exc, FeedError) else type(exc).__name__
        db.add(
            m.JobError(
                run_id=run.id,
                provider=exchange,
                item=day.isoformat(),
                code=artifact.error[:80],
                detail="Previous prices retained. Review source configuration or upload an official final UDiFF file.",
            )
        )
    await db.flush()
    return artifact


async def sync(db, run, counts, download=feed.download):
    from apps.worker.market import india_today

    counts["files_removed"] = await cleanup(db)
    params = run.parameters or {}
    day = date.fromisoformat(params["trade_date"]) if params.get("trade_date") else india_today()
    if day > india_today():
        raise FeedError("FUTURE_TRADE_DATE")
    exchanges = [params["exchange"]] if params.get("exchange") else ["NSE", "BSE"]
    notes = []
    for exchange in exchanges:
        artifact = await process_source(
            db, run, exchange, day, download=download, upload=params.get("upload_id")
        )
        result = artifact.counters or {}
        if artifact.status in ("RATE_LIMITED_RETRY_LATER", "BLOCKED_ADMIN_REQUIRED"):
            from packages.shared.job_diagnostics import guidance

            counts["failed"] += 1
            db.add(
                m.JobError(
                    run_id=run.id,
                    provider=exchange,
                    item=str(day),
                    code=artifact.status,
                    detail=guidance(artifact.status),
                )
            )
        if artifact.status not in ("SUCCESS", "PARTIAL"):
            notes.append(f"{exchange}: {artifact.error or artifact.status}")
        counts["fetched"] += result.get("rows", 0)
        counts["written"] += result.get("inserted", 0) + result.get("updated", 0)
        counts["unchanged"] += result.get("unchanged", 0)
        counts["failed"] += int(artifact.status == "FAILED") + result.get("rejected", 0)
        counts["providers"] += int(artifact.imported_at is not None)
        for key in ("matched", "inserted", "updated", "unmatched", "rejected"):
            counts[key] = counts.get(key, 0) + result.get(key, 0)
        # Sources commit independently; a BSE failure cannot roll back a successful NSE import.
        await db.commit()
    counts["listing_prices_populated"] = await refresh_listing_prices(db)
    return "; ".join(notes) or None

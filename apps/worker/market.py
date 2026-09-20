"""Shared market job orchestration used by Celery, authenticated routes and CLI."""

from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from apps.api.repository import METRICS
from apps.api.services import maintain_ipo
from packages.database import models as m
from packages.providers.market import (
    VERSION,
    FeedError,
    configuration,
    fetch_feed,
    fingerprint,
    normalize_record,
    safe_url,
)
from packages.shared.calculations import utc
from packages.shared.config import settings

JOBS = {
    "ipo-master": ("IPO discovery", "07:00 daily", ["ipos"]),
    "ipo-live": (
        "Subscription & GMP",
        "10:30, 12:30, 14:30, 16:00, 17:30 daily",
        ["subscriptions", "gmp"],
    ),
    "eod-prices": ("Closing prices", "18:15 trading days", ["prices"]),
    "results": ("Financial results", "19:00 daily", ["results"]),
    "reconcile": (
        "Evening reconciliation",
        "22:30 daily",
        ["ipos", "subscriptions", "gmp", "prices", "results"],
    ),
    "backfill": (
        "Historical backfill",
        "Manual · one company, one year per request",
        ["prices", "results"],
    ),
}


def india_today():
    return m.now().astimezone(ZoneInfo("Asia/Kolkata")).date()


def lifecycle(ipo, dates, guide, today):
    if ipo.raw_status in ("WITHDRAWN", "CANCELLED"):
        return ipo.raw_status
    if dates and dates.listing_date and today >= dates.listing_date:
        return "LISTING_TODAY" if today == dates.listing_date else "LISTED"
    if ipo.raw_status == "LISTED":
        return "LISTED"
    if dates and dates.open_date and today < dates.open_date:
        return "UPCOMING"
    if (
        dates
        and dates.open_date
        and dates.close_date
        and dates.open_date <= today <= dates.close_date
    ):
        return "OPEN"
    if dates and dates.close_date and today > dates.close_date:
        if dates.allotment_date:
            return "ALLOTMENT_COMPLETED" if today >= dates.allotment_date else "ALLOTMENT_PENDING"
        if guide and guide.schedule_status == "CONFIRMED" and guide.allotment_date:
            return "ALLOTMENT_COMPLETED" if today >= guide.allotment_date else "ALLOTMENT_PENDING"
        return "CLOSED"
    return (
        ipo.raw_status
        if ipo.raw_status
        in ("LISTED", "OPEN", "UPCOMING", "CLOSED", "ALLOTMENT_PENDING", "ALLOTMENT_COMPLETED")
        else "ANNOUNCED"
    )


async def reconcile_lifecycle(db, today):
    rows = (
        await db.execute(
            select(m.IPO, m.IPODate, m.ApplicantGuide)
            .outerjoin(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .outerjoin(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
        )
    ).all()
    for ipo, dates, guide in rows:
        # Preserve legacy manually maintained records until their source is integrated.
        if not ipo.source_provider:
            continue
        ipo.lifecycle = lifecycle(ipo, dates, guide, today)
        ipo.status = {
            "LISTING_TODAY": "LISTED",
            "ANNOUNCED": "UPCOMING",
            "ALLOTMENT_PENDING": "CLOSED",
            "ALLOTMENT_COMPLETED": "CLOSED",
            "WITHDRAWN": "CLOSED",
            "CANCELLED": "CLOSED",
        }.get(ipo.lifecycle, ipo.lifecycle)
    await db.flush()


async def match_company(db, data):
    matches = set()
    if data.isin:
        found = await db.scalar(select(m.Company.id).where(m.Company.isin == data.isin))
        if found:
            matches.add(found)
    for exchange, symbol in (("NSE", data.nse_symbol), ("BSE", data.bse_code)):
        if symbol:
            found = await db.scalar(
                select(m.Identifier.company_id).where(
                    m.Identifier.exchange == exchange, m.Identifier.ticker == symbol
                )
            )
            if found:
                matches.add(found)
    if len(matches) > 1:
        raise FeedError("IDENTIFIER_CONFLICT")
    company = await db.get(m.Company, next(iter(matches))) if matches else None
    if company and data.isin and company.isin and company.isin != data.isin:
        raise FeedError("IDENTIFIER_CONFLICT")
    return company


async def ingest_record(db, kind, data, provider, authority, raw_id):
    company = await match_company(db, data)
    digest = fingerprint(data.model_dump(mode="json"))
    if kind == "results":
        # A provider polling timestamp is not a new financial revision.
        digest = fingerprint(data.model_dump(mode="json", exclude={"source_timestamp"}))
    if kind == "ipos":
        if company:
            ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
            if not ipo:
                raise FeedError("IPO_MAPPING_MISSING")
            # Conflicting sources are retained for review. Same source can advance dates/status.
            if ipo.source_provider != provider:
                for key in (
                    "price_low",
                    "price_high",
                    "lot_size",
                    "issue_price",
                    "listing_price",
                    "issue_size",
                    "fresh_issue",
                    "ofs",
                ):
                    incoming = getattr(data.issue, key)
                    if incoming is not None and getattr(ipo, key) not in (None, incoming):
                        raise FeedError("SOURCE_CONFLICT")
                existing_dates = await db.scalar(
                    select(m.IPODate).where(m.IPODate.ipo_id == ipo.id)
                )
                if existing_dates and any(
                    getattr(data.issue, key) is not None
                    and getattr(existing_dates, key) not in (None, getattr(data.issue, key))
                    for key in ("open_date", "close_date", "listing_date")
                ):
                    raise FeedError("SOURCE_CONFLICT")
                if ipo.source_provider:
                    return False
            if ipo.source_timestamp and utc(data.source_timestamp) <= utc(ipo.source_timestamp):
                return False
            values = data.issue.model_copy(
                update={
                    "slug": company.slug,
                    "provider": provider,
                    "source_url": data.source_url,
                    "source_timestamp": data.source_timestamp,
                    "verification_status": "VERIFIED",
                    "baseline": None,
                    "ticker": None,
                }
            )
            # Missing feed fields must not erase existing values.
            for key in (
                "price_low",
                "price_high",
                "issue_price",
                "listing_price",
                "lot_size",
                "issue_size",
                "fresh_issue",
                "ofs",
            ):
                if getattr(values, key) is None:
                    setattr(values, key, getattr(ipo, key))
            dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
            for key in ("open_date", "close_date", "listing_date"):
                if dates and getattr(values, key) is None:
                    setattr(values, key, getattr(dates, key))
            await maintain_ipo(db, values, None, company.slug)
        else:
            values = data.issue.model_copy(
                update={
                    "provider": provider,
                    "source_url": data.source_url,
                    "verification_status": "VERIFIED",
                    "ticker": None,
                }
            )
            await maintain_ipo(db, values, None)
            company = await db.scalar(select(m.Company).where(m.Company.slug == values.slug))
            ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
        company.isin, company.company_type = data.isin or company.isin, data.company_type
        for key in (
            "registrar",
            "lead_managers",
            "retail_quota_pct",
            "qib_quota_pct",
            "nii_quota_pct",
            "employee_quota_pct",
            "shareholder_quota_pct",
        ):
            if getattr(data, key) is not None:
                setattr(ipo, key, getattr(data, key))
        dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
        for key in ("anchor_date", "allotment_date", "refund_date", "demat_credit_date"):
            if getattr(data, key) is not None:
                setattr(dates, key, getattr(data, key))
        for exchange, symbol in (("NSE", data.nse_symbol), ("BSE", data.bse_code)):
            if symbol and not await db.scalar(
                select(m.Identifier).where(
                    m.Identifier.company_id == company.id,
                    m.Identifier.exchange == exchange,
                    m.Identifier.ticker == symbol,
                )
            ):
                db.add(m.Identifier(company_id=company.id, exchange=exchange, ticker=symbol))
        ipo.raw_status, ipo.source_provider, ipo.source_timestamp = (
            data.official_status.upper(),
            provider,
            data.source_timestamp,
        )
        return True
    if not company:
        raise FeedError("UNMAPPED_IDENTIFIER")
    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
    if kind in ("subscriptions", "gmp") and not ipo:
        raise FeedError("IPO_MAPPING_MISSING")
    if kind == "subscriptions":
        categories = {k: v.model_dump(mode="json") for k, v in data.categories.items()}
        value_hash = fingerprint(categories)
        latest = await db.scalar(
            select(m.Subscription)
            .where(m.Subscription.ipo_id == ipo.id, m.Subscription.source_provider == provider)
            .order_by(m.Subscription.observed_at.desc())
            .limit(1)
        )
        if latest and (
            (
                latest.payload_hash == value_hash
                and utc(latest.observed_at).astimezone(ZoneInfo("Asia/Kolkata")).date()
                == data.source_timestamp.astimezone(ZoneInfo("Asia/Kolkata")).date()
            )
            or utc(latest.observed_at) > data.source_timestamp
        ):
            return False
        total = data.categories.get("total")
        db.add(
            m.Subscription(
                ipo_id=ipo.id,
                multiple=total.multiple if total else None,
                observed_at=data.source_timestamp,
                categories=categories,
                payload_hash=value_hash,
                source_provider=provider,
                source_url=data.source_url,
                raw_payload_id=raw_id,
            )
        )
    elif kind == "gmp":
        key = "feed:" + digest
        if await db.scalar(select(m.GMP.id).where(m.GMP.import_key == key)):
            return False
        db.add(
            m.GMP(
                ipo_id=ipo.id,
                value=data.value,
                observed_at=data.source_timestamp,
                import_key=key,
                source_url=data.source_url,
                source_provider=provider,
                raw_payload_id=raw_id,
            )
        )
    elif kind == "prices":
        if not ipo or ipo.status != "LISTED":
            return False
        price = await db.scalar(
            select(m.Price).where(
                m.Price.company_id == company.id, m.Price.price_date == data.price_date
            )
        )
        if price and price.source_provider != provider and price.close != data.close:
            raise FeedError("SOURCE_CONFLICT")
        if (
            price
            and price.source_timestamp
            and utc(price.source_timestamp) >= data.source_timestamp
        ):
            return False
        if not price:
            price = m.Price(company_id=company.id, price_date=data.price_date)
            db.add(price)
        for key in (
            "close",
            "open",
            "high",
            "low",
            "previous_close",
            "volume",
            "turnover",
            "source_url",
            "source_timestamp",
        ):
            setattr(price, key, getattr(data, key))
        price.source_provider, price.raw_payload_id = provider, raw_id
        await db.flush()
        history = (
            await db.scalars(
                select(m.Price).where(m.Price.company_id == company.id).order_by(m.Price.price_date)
            )
        ).all()
        latest = history[-1]
        recent = [p for p in history if p.price_date >= latest.price_date - timedelta(days=365)]
        snapshot = await db.scalar(
            select(m.PriceSnapshot).where(m.PriceSnapshot.company_id == company.id)
        )
        if not snapshot:
            snapshot = m.PriceSnapshot(company_id=company.id)
            db.add(snapshot)
        snapshot.cmp, snapshot.price_date = latest.close, latest.price_date
        snapshot.ath = max(p.high or p.close for p in history)
        snapshot.high_52w, snapshot.low_52w = max(p.high or p.close for p in recent), min(
            p.low or p.close for p in recent
        )
    elif kind == "results":
        table = m.Quarterly if data.period_type == "QUARTERLY" else m.Annual
        query = select(table).where(table.company_id == company.id)
        period = None
        if table == m.Quarterly:
            period = await db.scalar(
                select(m.Period).where(
                    m.Period.financial_year == data.financial_year, m.Period.quarter == data.quarter
                )
            )
            if not period:
                period = m.Period(financial_year=data.financial_year, quarter=data.quarter)
                db.add(period)
                await db.flush()
            query = query.where(table.period_id == period.id)
        else:
            query = query.where(table.financial_year == data.financial_year)
        prior = (await db.scalars(query.order_by(table.revision.desc()))).all()
        if any(p.payload_hash == digest for p in prior):
            return False
        same = next((p for p in prior if p.statement_type == data.statement_type), None)
        if same and same.source_provider != provider:
            raise FeedError("SOURCE_CONFLICT")
        if same and same.source_timestamp and utc(same.source_timestamp) > data.source_timestamp:
            return False
        record = table(
            company_id=company.id,
            revision=max((p.revision for p in prior), default=0) + 1,
            source_url=data.source_url,
            source_provider=provider,
            source_timestamp=data.source_timestamp,
            statement_type=data.statement_type,
            period_start=data.period_start,
            period_end=data.period_end,
            filing_id=data.filing_id,
            payload_hash=digest,
            raw_payload_id=raw_id,
            parser_version=VERSION,
            industry_metrics={
                k: str(v) if v is not None else None for k, v in data.industry_metrics.items()
            },
            **{key: getattr(data, key) for key in METRICS},
        )
        if table == m.Quarterly:
            record.period_id, record.import_key, record.verification_status = (
                period.id,
                "feed:" + digest,
                "VERIFIED",
            )
        else:
            record.financial_year = data.financial_year
        db.add(record)
    await db.flush()
    if kind == "subscriptions":
        snapshot = await db.scalar(
            select(m.Subscription)
            .where(m.Subscription.ipo_id == ipo.id, m.Subscription.source_provider == provider)
            .order_by(m.Subscription.observed_at.desc(), m.Subscription.created_at.desc())
            .limit(1)
        )
        day = data.source_timestamp.astimezone(ZoneInfo("Asia/Kolkata")).date()
        daily = await db.scalar(
            select(m.SubscriptionDay).where(
                m.SubscriptionDay.company_id == company.id,
                m.SubscriptionDay.subscription_date == day,
                m.SubscriptionDay.exchange == authority,
            )
        )
        if not daily:
            daily = m.SubscriptionDay(
                company_id=company.id,
                subscription_date=day,
                exchange=authority,
                subscription_id=snapshot.id,
            )
            db.add(daily)
            await db.flush()
        else:
            daily.subscription_id = snapshot.id
            await db.execute(
                delete(m.SubscriptionDetail).where(m.SubscriptionDetail.day_id == daily.id)
            )
        for category, value in data.categories.items():
            db.add(
                m.SubscriptionDetail(
                    day_id=daily.id,
                    category=category,
                    multiple=value.multiple,
                    bid_shares=value.bid_shares,
                    offered_shares=value.offered_shares,
                )
            )
        await db.flush()
    return True


async def acquire(db, owner):
    # One ingestion writer protects overlapping reconciliation and individual jobs as well.
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    lease_now = utc(await db.scalar(select(func.current_timestamp())))
    statement = insert(m.JobLock).values(
        name="market-writer", owner=owner, expires_at=lease_now + timedelta(minutes=6)
    )
    statement = statement.on_conflict_do_update(
        index_elements=["name"],
        set_={"owner": owner, "expires_at": lease_now + timedelta(minutes=6)},
        where=m.JobLock.expires_at < lease_now,
    ).returning(m.JobLock.owner)
    return await db.scalar(statement) == owner


async def run_job(db, run, fetch=fetch_feed):
    if run.job_name.startswith(("collect-", "publish-", "sync-")):
        from apps.worker.exchange_pipeline import run_pipeline

        return await run_pipeline(db, run)
    run_id = run.id
    if run.status != "QUEUED":
        return run
    if not await acquire(db, run.id):
        run.status, run.error, run.finished_at = "SKIPPED", "Another market job is running", m.now()
        await db.commit()
        return run
    run.status, run.started_at = "RUNNING", m.now()
    await db.commit()
    counters = {"fetched": 0, "written": 0, "unchanged": 0, "failed": 0, "providers": 0}
    notes = []
    try:
        controls = await db.get(m.SchedulerControl, run.job_name)
        if controls and controls.paused:
            notes.append("PAUSED")
        else:
            feeds = configuration(settings().market_feeds_json)
            today = india_today()
            await reconcile_lifecycle(db, today)
            open_ipo = await db.scalar(
                select(m.IPO.id)
                .join(m.Company)
                .where(m.IPO.status == "OPEN", m.Company.is_demo.is_(False))
                .limit(1)
            )
            for kind in JOBS[run.job_name][2]:
                if kind in ("subscriptions", "gmp") and not open_ipo:
                    notes.append("NO_OPEN_IPOS")
                    continue
                if kind == "prices" and run.job_name != "backfill":
                    holidays = settings().trading_holidays.split(",")
                    if today.weekday() >= 5 or today.isoformat() in holidays:
                        notes.append("NOT_EXPECTED: market holiday/weekend")
                        continue
                    if settings().trading_calendar_year != today.year:
                        notes.append("TRADING_CALENDAR_REQUIRED")
                        continue
                enabled = [
                    (name, conf) for name, conf in feeds.get(kind, {}).items() if conf.enabled
                ]
                enabled.sort(key=lambda item: (0 if item[1].authority == "NSE" else 1, item[0]))
                if not enabled:
                    notes.append(f"NOT_CONFIGURED: {kind}")
                for provider, config in enabled:
                    try:
                        params = {
                            "from": (today - timedelta(days=7)).isoformat(),
                            "to": today.isoformat(),
                            **(run.parameters or {}),
                        }
                        raw, records = await fetch(config, params)
                        payload = m.RawPayload(
                            provider=provider,
                            data_type=kind,
                            requested_url=safe_url(config.url),
                            http_status=200,
                            payload_text=raw,
                            payload_hash=fingerprint(raw),
                            parser_version=VERSION,
                        )
                        db.add(payload)
                        await db.flush()
                        counters["providers"] += 1
                        if not records and kind == "prices":
                            notes.append("SOURCE_NOT_READY")
                        for index, value in enumerate(records):
                            counters["fetched"] += 1
                            try:
                                async with db.begin_nested():
                                    data = normalize_record(kind, value, config)
                                    if kind != "ipos":
                                        company = await match_company(db, data)
                                        if not company or company.is_demo:
                                            counters["unchanged"] += 1
                                            continue  # Bulk feeds contain securities outside our universe.
                                        if (run.parameters or {}).get(
                                            "company_id"
                                        ) and company.id != run.parameters["company_id"]:
                                            continue
                                        if kind in ("subscriptions", "gmp"):
                                            target_ipo = await db.scalar(
                                                select(m.IPO).where(m.IPO.company_id == company.id)
                                            )
                                            if not target_ipo or target_ipo.status != "OPEN":
                                                continue
                                        if (
                                            kind == "prices"
                                            and run.job_name != "backfill"
                                            and data.price_date != today
                                        ):
                                            notes.append("SOURCE_NOT_READY")
                                            continue
                                        if run.job_name == "backfill":
                                            observed_date = (
                                                data.price_date
                                                if kind == "prices"
                                                else data.period_end
                                            )
                                            if (
                                                not run.parameters["from"]
                                                <= observed_date.isoformat()
                                                <= run.parameters["to"]
                                            ):
                                                continue
                                    changed = await ingest_record(
                                        db, kind, data, provider, config.authority, payload.id
                                    )
                                    counters["written" if changed else "unchanged"] += 1
                            except Exception as exc:
                                counters["failed"] += 1
                                code = (
                                    str(exc) if isinstance(exc, FeedError) else type(exc).__name__
                                )
                                db.add(
                                    m.JobError(
                                        run_id=run.id,
                                        provider=provider,
                                        item=f"{kind}:{index}",
                                        code=code[:80],
                                        detail="Record rejected; inspect the stored raw payload and identifier mapping.",
                                    )
                                )
                                if code in (
                                    "SOURCE_CONFLICT",
                                    "IDENTIFIER_CONFLICT",
                                    "UNMAPPED_IDENTIFIER",
                                ):
                                    db.add(
                                        m.QualityIssue(
                                            kind="CONFLICT",
                                            detail=f"{provider}: {code}; inspect market job {run.id}",
                                        )
                                    )
                        await db.flush()
                    except Exception as exc:
                        counters["failed"] += 1
                        code = str(exc) if isinstance(exc, FeedError) else type(exc).__name__
                        if isinstance(exc, FeedError) and exc.raw is not None:
                            db.add(
                                m.RawPayload(
                                    provider=provider,
                                    data_type=kind,
                                    requested_url=safe_url(config.url),
                                    http_status=200,
                                    payload_text=exc.raw,
                                    payload_hash=fingerprint(exc.raw),
                                    parser_version=VERSION,
                                )
                            )
                        db.add(
                            m.JobError(
                                run_id=run.id,
                                provider=provider,
                                item=kind,
                                code=code[:80],
                                detail="Provider request failed; previous data retained.",
                            )
                        )
            await reconcile_lifecycle(db, today)
        run.status = (
            ("PARTIAL" if counters["providers"] else "FAILED")
            if counters["failed"]
            else "SUCCESS" if counters["providers"] else "SKIPPED"
        )
        if notes and run.status == "SUCCESS":
            run.status = "PARTIAL"
        run.error = "; ".join(dict.fromkeys(notes)) or (
            "Some records failed; open run details" if counters["failed"] else None
        )
    except Exception:
        await db.rollback()
        run = await db.get(m.ImportRun, run_id)
        run.status, run.error = "FAILED", "Job failed; inspect worker logs and configuration"
        counters["written"] = 0
    run.counters, run.finished_at = counters, m.now()
    await db.execute(
        delete(m.JobLock).where(m.JobLock.name == "market-writer", m.JobLock.owner == run.id)
    )
    from apps.api.cache import commit_with_invalidation

    await commit_with_invalidation(db)
    return run


async def create_run(db, job, trigger, parameters=None):
    run = m.ImportRun(
        key=f"market:{uuid4()}",
        provider="market-feeds",
        job_name=job,
        trigger=trigger,
        status="QUEUED",
        parameters=parameters or {},
    )
    db.add(run)
    await db.commit()
    return run

from fastapi import HTTPException
from sqlalchemy import select

from apps.api.repository import METRICS, record
from packages.database import models as m
from packages.shared.calculations import utc


async def provenance(db, entity, data):
    source = await db.scalar(select(m.Source).where(m.Source.name == data.provider))
    if not source:
        source = m.Source(name=data.provider, category="manual")
        db.add(source)
        await db.flush()
    for key, value in data.model_dump().items():
        if value is not None and key not in (
            "provider",
            "source_url",
            "source_timestamp",
            "verification_status",
            "import_key",
            "baseline",
        ):
            db.add(
                m.Provenance(
                    entity_type=entity.__tablename__,
                    entity_id=entity.id,
                    field_name=key,
                    source_id=source.id,
                    source_url=data.source_url,
                    source_timestamp=data.source_timestamp,
                    verification_status=data.verification_status,
                    verified_at=m.now() if data.verification_status == "VERIFIED" else None,
                )
            )


def audit(db, admin_id, action, entity, before=None):
    db.add(
        m.Audit(
            admin_id=admin_id,
            action=action,
            entity_id=entity.id,
            changes={"before": before, "after": record(entity)},
        )
    )


async def maintain_ipo(db, data, user_id, slug=None):
    company = await db.scalar(select(m.Company).where(m.Company.slug == (slug or data.slug)))
    if company and not slug:
        raise HTTPException(409, "Company slug already exists")
    if slug and not company:
        raise HTTPException(404, "Company not found")
    if slug and data.slug != slug:
        raise HTTPException(422, "A public slug cannot be changed")
    if slug and data.baseline is not None:
        raise HTTPException(
            409, "IPO baseline is immutable; later results belong to quarterly records"
        )
    sector = await db.scalar(select(m.Sector).where(m.Sector.name == data.sector))
    if not sector:
        sector = m.Sector(name=data.sector)
        db.add(sector)
        await db.flush()
    before = record(company) if company else None
    if not company:
        company = m.Company(slug=data.slug, name=data.name)
        db.add(company)
    company.name, company.sector_id, company.board = data.name, sector.id, data.board
    company.screener_url, company.exchange_url = data.screener_url, data.exchange_url
    await db.flush()
    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
    before_ipo = record(ipo) if ipo else None
    if not ipo:
        ipo = m.IPO(company_id=company.id, status=data.status)
        db.add(ipo)
    for key in (
        "status",
        "price_low",
        "price_high",
        "issue_price",
        "listing_price",
        "lot_size",
        "issue_size",
        "fresh_issue",
        "ofs",
    ):
        setattr(ipo, key, getattr(data, key))
    ipo.quality = data.verification_status
    await db.flush()
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    before_dates = record(dates) if dates else None
    if not dates:
        dates = m.IPODate(ipo_id=ipo.id)
        db.add(dates)
    dates.open_date, dates.close_date, dates.listing_date = (
        data.open_date,
        data.close_date,
        data.listing_date,
    )
    if data.ticker:
        identifier = await db.scalar(
            select(m.Identifier).where(
                m.Identifier.company_id == company.id, m.Identifier.exchange == data.exchange
            )
        )
        if not identifier:
            identifier = m.Identifier(
                company_id=company.id, ticker=data.ticker, exchange=data.exchange
            )
            db.add(identifier)
        identifier.ticker = data.ticker
    if data.baseline is not None:
        db.add(
            m.Baseline(
                ipo_id=ipo.id,
                **data.baseline.model_dump(),
                pe=data.baseline_pe,
                market_cap=data.baseline_market_cap,
            )
        )
    if data.rhp_url:
        existing = await db.scalar(
            select(m.Document).where(
                m.Document.ipo_id == ipo.id,
                m.Document.kind == "RHP",
                m.Document.url == data.rhp_url,
            )
        )
        if not existing:
            db.add(m.Document(ipo_id=ipo.id, kind="RHP", url=data.rhp_url))
    await provenance(db, ipo, data)
    await db.flush()
    db.add(
        m.Audit(
            admin_id=user_id,
            action="ipo.update" if slug else "ipo.create",
            entity_id=company.id,
            changes={
                "before": {"company": before, "ipo": before_ipo, "dates": before_dates},
                "after": {"company": record(company), "ipo": record(ipo), "dates": record(dates)},
            },
        )
    )
    return company


async def add_quarter(db, slug, data, user_id=None):
    company = await db.scalar(select(m.Company).where(m.Company.slug == slug))
    if not company:
        raise HTTPException(404, "Company not found")
    existing = await db.scalar(select(m.Quarterly).where(m.Quarterly.import_key == data.import_key))
    if existing:
        if existing.company_id != company.id:
            raise HTTPException(409, "Import key belongs to a different company")
        original_period = await db.get(m.Period, existing.period_id)
        if (
            any(getattr(existing, k) != getattr(data, k) for k in METRICS)
            or original_period.financial_year != data.financial_year
            or original_period.quarter != data.quarter
            or existing.source_url != data.source_url
            or existing.verification_status != data.verification_status
        ):
            raise HTTPException(409, "Import key was already used with different values")
        return existing, False
    period = await db.scalar(
        select(m.Period).where(
            m.Period.financial_year == data.financial_year, m.Period.quarter == data.quarter
        )
    )
    if not period:
        period = m.Period(financial_year=data.financial_year, quarter=data.quarter)
        db.add(period)
        await db.flush()
    latest = await db.scalar(
        select(m.Quarterly)
        .where(m.Quarterly.company_id == company.id, m.Quarterly.period_id == period.id)
        .order_by(m.Quarterly.revision.desc())
        .limit(1)
    )
    if (
        latest
        and latest.verification_status == "VERIFIED"
        and data.verification_status != "VERIFIED"
    ):
        raise HTTPException(409, "A verified result cannot be replaced by an unverified result")
    quarter = m.Quarterly(
        company_id=company.id,
        period_id=period.id,
        revision=(latest.revision + 1 if latest else 1),
        **{k: getattr(data, k) for k in METRICS},
        source_url=data.source_url,
        verification_status=data.verification_status,
        import_key=data.import_key,
    )
    db.add(quarter)
    await db.flush()
    await provenance(db, company, data)
    audit(
        db,
        user_id,
        "quarter.revision" if latest else "quarter.create",
        quarter,
        record(latest) if latest else None,
    )
    return quarter, True


async def add_gmp(db, slug, data, user_id=None):
    company = await db.scalar(select(m.Company).where(m.Company.slug == slug))
    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id)) if company else None
    if not ipo:
        raise HTTPException(404, "IPO not found")
    existing = await db.scalar(select(m.GMP).where(m.GMP.import_key == data.import_key))
    if existing:
        if existing.ipo_id != ipo.id:
            raise HTTPException(409, "Import key belongs to a different IPO")
        if (
            existing.value != data.value
            or utc(existing.observed_at) != utc(data.observed_at)
            or existing.source_url != data.source_url
        ):
            raise HTTPException(409, "Import key was already used with different values")
        return existing, False
    gmp = m.GMP(
        ipo_id=ipo.id,
        value=data.value,
        observed_at=data.observed_at,
        source_url=data.source_url,
        import_key=data.import_key,
    )
    db.add(gmp)
    await db.flush()
    await provenance(db, ipo, data)
    audit(db, user_id, "gmp.create", gmp)
    return gmp, True

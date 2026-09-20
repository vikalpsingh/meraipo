from sqlalchemy import select

from apps.api.schemas import DocumentInput, GMPInput, IPOInput, PriceInput, QuarterInput
from apps.api.services import add_gmp, add_quarter, maintain_ipo
from packages.database import models as m
from packages.providers.contracts import Batch


async def ingest(db, batch: Batch, key: str):
    run = await db.scalar(select(m.ImportRun).where(m.ImportRun.key == key))
    if run and run.status in ("SUCCEEDED", "SKIPPED", "CONFLICT"):
        return {"status": run.status, "duplicate": True}
    if not run:
        run = m.ImportRun(
            key=key, provider=batch.provider, status="RUNNING", request_id=batch.request_id
        )
        db.add(run)
    run.status = "RUNNING"
    conflicts = 0
    for raw in batch.records:
        payload = dict(raw)
        slug = payload.pop("company_slug", None)
        company = await db.scalar(
            select(m.Company).where(m.Company.slug == (slug or payload.get("slug")))
        )
        if batch.kind == "ipos":
            data = IPOInput.model_validate(payload)
            if company:
                existing = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
                if existing and any(
                    getattr(existing, k) != getattr(data, k)
                    for k in ("price_low", "price_high", "issue_price", "status")
                ):
                    db.add(
                        m.QualityIssue(
                            company_id=company.id,
                            kind="CONFLICT",
                            detail=f"{batch.provider}: IPO fields differ; admin review required.",
                        )
                    )
                    conflicts += 1
                continue
            await maintain_ipo(db, data, None)
        elif batch.kind == "results":
            data = QuarterInput.model_validate(payload)
            if company:
                period = await db.scalar(
                    select(m.Period).where(
                        m.Period.financial_year == data.financial_year,
                        m.Period.quarter == data.quarter,
                    )
                )
                prior = (
                    await db.scalar(
                        select(m.Quarterly)
                        .where(
                            m.Quarterly.company_id == company.id, m.Quarterly.period_id == period.id
                        )
                        .order_by(m.Quarterly.revision.desc())
                        .limit(1)
                    )
                    if period
                    else None
                )
                if prior and prior.import_key != data.import_key:
                    db.add(
                        m.QualityIssue(
                            company_id=company.id,
                            kind="CONFLICT",
                            detail=f"{batch.provider}: a result already exists for this period; review before creating a revision.",
                        )
                    )
                    conflicts += 1
                    continue
            await add_quarter(db, slug, data)
        elif batch.kind == "gmp":
            await add_gmp(db, slug, GMPInput.model_validate(payload))
        elif batch.kind == "prices":
            from datetime import timedelta

            if not company:
                raise ValueError("A price must reference a known company")
            data = PriceInput.model_validate(payload)
            prior = await db.scalar(
                select(m.Price).where(
                    m.Price.company_id == company.id, m.Price.price_date == data.price_date
                )
            )
            if prior:
                if prior.close != data.close or prior.high != data.high or prior.low != data.low:
                    db.add(
                        m.QualityIssue(
                            company_id=company.id,
                            kind="CONFLICT",
                            detail=f"{batch.provider}: an EOD price differs for {data.price_date}",
                        )
                    )
                    conflicts += 1
                continue
            db.add(
                m.Price(
                    company_id=company.id,
                    price_date=data.price_date,
                    close=data.close,
                    high=data.high,
                    low=data.low,
                    source_url=data.source_url,
                )
            )
            await db.flush()
            history = (
                await db.scalars(
                    select(m.Price)
                    .where(m.Price.company_id == company.id)
                    .order_by(m.Price.price_date)
                )
            ).all()
            recent = [
                p for p in history if p.price_date >= history[-1].price_date - timedelta(days=365)
            ]
            snapshot = await db.scalar(
                select(m.PriceSnapshot).where(m.PriceSnapshot.company_id == company.id)
            )
            if not snapshot:
                snapshot = m.PriceSnapshot(company_id=company.id)
                db.add(snapshot)
            snapshot.cmp, snapshot.price_date = history[-1].close, history[-1].price_date
            snapshot.ath = max(p.high or p.close for p in history)
            snapshot.high_52w = max(p.high or p.close for p in recent)
            snapshot.low_52w = min(p.low or p.close for p in recent)
            from apps.api.services import provenance

            await provenance(db, company, data)
        elif batch.kind == "documents":
            data = DocumentInput.model_validate(payload)
            if not company:
                raise ValueError("Document must reference a known company")
            ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
            existing = await db.scalar(
                select(m.Document).where(
                    m.Document.ipo_id == ipo.id,
                    m.Document.kind == data.kind,
                    m.Document.url == data.source_url,
                )
            )
            if not existing:
                db.add(m.Document(ipo_id=ipo.id, kind=data.kind, url=data.source_url))
        else:
            raise ValueError(f"No enabled ingestion adapter for {batch.kind}")
    run.status = "CONFLICT" if conflicts else "SUCCEEDED" if batch.records else "SKIPPED"
    run.error = f"{conflicts} conflicts require review" if conflicts else None
    await db.flush()
    return {"status": run.status, "duplicate": False}

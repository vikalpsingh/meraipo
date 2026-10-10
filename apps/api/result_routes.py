"""Financial import review, using existing admin sessions and CSRF protection."""

import hashlib
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from apps.api.cache import commit_with_invalidation
from apps.api.repository import record
from apps.api.schemas import Input
from apps.api.security import admin
from apps.worker import results as worker
from apps.worker.market import acquire
from packages.database import models as m
from packages.database.session import get_session
from packages.providers import results as feed

router = APIRouter(prefix="/admin/results")


class Schedule(Input):
    enabled: bool
    schedule: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


@router.get("")
async def overview(auth=Depends(admin), db=Depends(get_session)):
    sources = (await db.scalars(select(m.ResultSource))).all()
    filings = (
        await db.scalars(
            select(m.ResultFiling).order_by(m.ResultFiling.created_at.desc()).limit(100)
        )
    ).all()
    checkpoints = (
        await db.scalars(
            select(m.ResultHistory).order_by(m.ResultHistory.completed_at.desc()).limit(100)
        )
    ).all()
    official_sources = (await db.scalars(select(m.CompanyResultSource))).all()
    companies = (
        await db.scalars(
            select(m.Company).where(
                m.Company.is_demo.is_(False),
                m.Company.id.in_(
                    select(m.Identifier.company_id).where(m.Identifier.exchange == "BSE")
                ),
                ~m.Company.id.in_(
                    select(m.Identifier.company_id).where(m.Identifier.exchange == "NSE")
                ),
            )
        )
    ).all()
    return {
        "official_sources": [record(s) for s in official_sources],
        "bse_companies": [{"id": c.id, "name": c.name} for c in companies],
        "checkpoints": [record(c) for c in checkpoints],
        "sources": [record(s) for s in sources],
        "filings": [record(f) for f in filings],
        "timezone": "Asia/Kolkata",
    }


@router.put("/sources/{exchange}")
async def configure(
    exchange: Literal["BSE", "NSE"], data: Schedule, auth=Depends(admin), db=Depends(get_session)
):
    state = await db.get(m.ResultSource, exchange)
    if not state:
        state = m.ResultSource(exchange=exchange)
        db.add(state)
    state.enabled, state.schedule = data.enabled, data.schedule
    control = await db.get(m.SchedulerControl, f"sync-results-{exchange.lower()}")
    if control:
        control.schedule_times = [data.schedule]
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.result_source",
            entity_id=exchange,
            changes=data.model_dump(),
        )
    )
    await db.commit()
    return {"saved": True}


@router.post("/discovery")
async def discovery(
    request: Request, apply: bool = False, auth=Depends(admin), db=Depends(get_session)
):
    try:
        rows = feed.bse_csv(await request.body())
    except (ValueError, feed.FeedError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if apply:
        for row in rows:
            await worker.store_filing(db, "BSE", row)
        await db.commit()
    return {"items": rows, "published": False, "saved": apply}


class ManualFiling(Input):
    exchange: Literal["BSE", "NSE"]
    identifier: str = Field(min_length=1, max_length=40)
    announced_at: datetime
    basis: Literal["STANDALONE", "CONSOLIDATED"]
    source_url: str
    period_end: str | None = None


@router.post("/filings")
async def filing(data: ManualFiling, auth=Depends(admin), db=Depends(get_session)):
    try:
        official = False
        try:
            feed.exchange_url(data.source_url)
        except feed.FeedError:
            mapping = await db.scalar(
                select(m.Identifier).where(
                    m.Identifier.exchange == data.exchange, m.Identifier.ticker == data.identifier
                )
            )
            source = await db.get(m.CompanyResultSource, mapping.company_id) if mapping else None
            if (
                data.exchange != "BSE"
                or not source
                or not source.enabled
                or not data.source_url.startswith(source.document_prefix)
            ):
                raise
            from packages.providers.company_results import approved_url

            approved_url(data.source_url, source.page_url)
            official = True
        if data.announced_at.tzinfo is None:
            raise ValueError("Filing timestamp requires timezone")
        metadata = data.model_dump(mode="json", exclude={"exchange"})
        metadata["attachments"] = [data.source_url]
        if official:
            metadata["origin"] = "OFFICIAL_COMPANY"
        row, _ = await worker.store_filing(db, data.exchange, metadata)
        await db.commit()
        return record(row)
    except (ValueError, feed.FeedError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/filings/{filing_id}/preview")
async def upload(filing_id: str, request: Request, auth=Depends(admin), db=Depends(get_session)):
    filing = await db.get(m.ResultFiling, filing_id)
    if not filing:
        raise HTTPException(404, "Filing not found")
    content = await request.body()
    try:
        attachment = await worker.store_attachment(
            db, filing, content, filing.metadata_json["source_url"]
        )
        await db.commit()
        parsed = await worker.preview(db, filing, content)
        return {
            "attachment_id": attachment.id,
            "checksum": attachment.checksum,
            "items": parsed,
            "publishable": True,
        }
    except (ValueError, feed.FeedError) as exc:
        filing.status, filing.error = "PARSING_REVIEW_REQUIRED", str(exc)
        await db.commit()
        return {"items": [], "publishable": False, "error": str(exc)}


class Publish(Input):
    attachment_id: str
    checksum: str


@router.post("/publish")
async def publish(data: Publish, auth=Depends(admin), db=Depends(get_session)):
    attachment = await db.get(m.ResultAttachment, data.attachment_id)
    if not attachment or hashlib.sha256(attachment.content).hexdigest() != data.checksum:
        raise HTTPException(422, "Preview the unchanged original before publishing")
    filing = await db.get(m.ResultFiling, attachment.filing_id)
    owner = attachment.id
    if not await acquire(db, owner):
        raise HTTPException(409, "Another market job is running")
    try:
        parsed = await worker.preview(db, filing, attachment.content)
        async with db.begin_nested():
            count = await worker.publish(db, filing, parsed)
        from sqlalchemy import delete

        await db.execute(delete(m.JobLock).where(m.JobLock.owner == owner))
        await commit_with_invalidation(db)
        return {"published": count}
    except (ValueError, feed.FeedError) as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.get("/attachments/{attachment_id}")
async def original(attachment_id: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.ResultAttachment, attachment_id)
    if not row:
        raise HTTPException(404, "Original not found")
    return Response(
        row.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{row.checksum}.bin"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class Mapping(Input):
    company_id: str


@router.post("/filings/{filing_id}/mapping")
async def mapping(filing_id: str, data: Mapping, auth=Depends(admin), db=Depends(get_session)):
    filing = await db.get(m.ResultFiling, filing_id)
    company = await db.get(m.Company, data.company_id)
    if not filing or not company or company.is_demo:
        raise HTTPException(422, "Choose a tracked company and filing")
    existing = await db.scalar(
        select(m.Identifier).where(
            m.Identifier.exchange == filing.exchange, m.Identifier.ticker == filing.identifier
        )
    )
    if existing and existing.company_id != company.id:
        raise HTTPException(409, "Identifier already belongs to another company")
    if not existing:
        db.add(
            m.Identifier(company_id=company.id, exchange=filing.exchange, ticker=filing.identifier)
        )
    filing.company_id, filing.status = company.id, "AWAITING_PROCESSING"
    await db.commit()
    return {"mapped": True}


@router.get("/filings/{filing_id}/attachments")
async def attachments(filing_id: str, auth=Depends(admin), db=Depends(get_session)):
    rows = (
        await db.scalars(
            select(m.ResultAttachment).where(m.ResultAttachment.filing_id == filing_id)
        )
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "checksum": r.checksum,
                "type": r.content_type,
                "source_url": r.source_url,
                "retrieved_at": r.created_at,
            }
            for r in rows
        ]
    }


class OfficialSource(Input):
    page_url: str = Field(max_length=2000)
    document_prefix: str = Field(max_length=2000)
    enabled: bool
    official_source_confirmed: bool


@router.put("/official-sources/{company_id}")
async def configure_official(
    company_id: str, data: OfficialSource, auth=Depends(admin), db=Depends(get_session)
):
    from packages.providers.company_results import approved_url, public_address

    company = await db.get(m.Company, company_id)
    if not company or company.is_demo:
        raise HTTPException(422, "Choose a tracked BSE-only company")
    identifiers = await worker.company_identifiers(db, company)
    if not identifiers["BSE"] or identifiers["NSE"] or not data.official_source_confirmed:
        raise HTTPException(
            422, "Confirm the official investor-relations source for a BSE-only company"
        )
    try:
        approved_url(data.page_url)
        approved_url(data.document_prefix, data.page_url)
        if not data.document_prefix.endswith("/"):
            raise ValueError("Document directory must end with /")
        await public_address(data.page_url)
    except (ValueError, OSError, feed.FeedError) as exc:
        raise HTTPException(
            422, "Use an approved public HTTPS page and a document directory on the same host"
        ) from exc
    source = await db.get(m.CompanyResultSource, company_id)
    if not source:
        source = m.CompanyResultSource(company_id=company_id)
        db.add(source)
    source.page_url, source.document_prefix, source.enabled = (
        data.page_url,
        data.document_prefix,
        data.enabled,
    )
    source.approved_by, source.approved_at = auth[0].id, m.now()
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="results.official_source",
            entity_id=company_id,
            changes=data.model_dump(),
        )
    )
    await db.commit()
    return {"saved": True}

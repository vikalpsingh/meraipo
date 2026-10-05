"""Authenticated preview, import, bounded backfill and diagnostics."""

import csv
import hashlib
import io
import json
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from apps.api.repository import record
from apps.api.schemas import Input
from apps.api.security import admin
from apps.worker.bhavcopy import cleanup, preview, save_original
from apps.worker.market import create_run, india_today
from packages.database import models as m
from packages.database.session import get_session
from packages.providers import bhavcopy as feed
from packages.shared.market_config import load_market_settings, market_settings_context

router = APIRouter(prefix="/admin/bhavcopy")


class SourceSettings(Input):
    sources_json: str


@router.put("/sources")
async def save_sources(data: SourceSettings, auth=Depends(admin), db=Depends(get_session)):
    try:
        parsed = feed.sources(data.sources_json)
    except (ValueError, feed.FeedError) as exc:
        raise HTTPException(422, str(exc)) from exc
    row = await db.get(m.MarketConfiguration, "market")
    if not row:
        row = m.MarketConfiguration(id="market", values={})
        db.add(row)
    row.values = {
        **row.values,
        "bhavcopy_sources_json": json.dumps(
            {k: v.model_dump(mode="json") for k, v in parsed.items()}
        ),
    }
    row.updated_by = auth[0].id
    from apps.api.cache import commit_with_invalidation

    await commit_with_invalidation(db)
    return {"saved": True}


@router.get("")
async def overview(auth=Depends(admin), db=Depends(get_session)):
    config = await load_market_settings(db)
    files = (
        await db.scalars(
            select(m.BhavcopyFile).order_by(m.BhavcopyFile.created_at.desc()).limit(100)
        )
    ).all()
    return {
        "schedule": "19:00, 20:00, 22:00",
        "timezone": "Asia/Kolkata",
        "retention_days": 7,
        "sources": [
            {
                "exchange": exchange,
                **source.model_dump(mode="json"),
                "status": (
                    "DISABLED"
                    if not source.enabled
                    else (
                        "CONFIGURED"
                        if source.url_template and source.verified_on
                        else "SOURCE_CONFIGURATION_REQUIRED"
                    )
                ),
                "last_success": next(
                    (record(f) for f in files if f.exchange == exchange and f.imported_at), None
                ),
            }
            for exchange, source in feed.sources(config.bhavcopy_sources_json).items()
        ],
        "files": [record(f) for f in files],
    }


@router.post("/preview")
async def upload_preview(
    request: Request,
    exchange: Literal["NSE", "BSE"],
    trade_date: date,
    auth=Depends(admin),
    db=Depends(get_session),
):
    if trade_date > india_today():
        raise HTTPException(422, "Choose a completed trading date")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > feed.MAX_DOWNLOAD:
            raise HTTPException(413, "File exceeds 20 MB")
    try:
        async with market_settings_context(db):
            rows, errors, counters = await preview(db, bytes(content), exchange, trade_date)
            # Preview storage also follows retention. No prices are written here.
            await cleanup(db)
            checksum = hashlib.sha256(content).hexdigest()
            path = save_original(content, exchange, trade_date, checksum)
            artifact = m.BhavcopyFile(
                exchange=exchange,
                trade_date=trade_date,
                source_url="manual-upload",
                checksum=checksum,
                path=path,
                status="PREVIEW",
                errors=errors,
                counters=counters,
            )
            db.add(artifact)
            await db.commit()
        return {
            "id": artifact.id,
            "checksum": checksum,
            "counters": counters,
            "errors": errors[:100],
            "sample": rows[:20],
        }
    except (ValueError, feed.FeedError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Run(Input):
    from_date: date
    to_date: date
    exchange: Literal["NSE", "BSE"] | None = None
    upload_id: str | None = None


@router.post("/run", status_code=202)
async def run_dates(data: Run, auth=Depends(admin), db=Depends(get_session)):
    if data.to_date > india_today() or not 0 <= (data.to_date - data.from_date).days <= 30:
        raise HTTPException(422, "Choose at most 31 dates, ending today or earlier")
    if data.upload_id:
        artifact = await db.get(m.BhavcopyFile, data.upload_id)
        if (
            not artifact
            or artifact.status != "PREVIEW"
            or artifact.purged_at
            or not (
                artifact.exchange == data.exchange
                and artifact.trade_date == data.from_date == data.to_date
            )
        ):
            raise HTTPException(422, "Preview the original file for this exchange and date first")
    runs = []
    for offset in range((data.to_date - data.from_date).days + 1):
        params = {"trade_date": (data.from_date + timedelta(days=offset)).isoformat()}
        if data.exchange:
            params["exchange"] = data.exchange
        if data.upload_id:
            params["upload_id"] = data.upload_id
        runs.append(await create_run(db, "sync-prices", "manual", params))
    try:
        from celery import chain

        from apps.worker.tasks import market_job

        # One date per bounded worker execution, sequential to avoid self-contention.
        chain(*(market_job.si(run.id) for run in runs)).apply_async()
    except Exception:
        for run in runs:
            run.status, run.error = "FAILED", "QUEUE_UNAVAILABLE"
        await db.commit()
        raise HTTPException(503, "Queue unavailable; attempts recorded") from None
    return {"ids": [run.id for run in runs]}


@router.get("/{file_id}/errors.csv")
async def error_report(file_id: str, auth=Depends(admin), db=Depends(get_session)):
    artifact = await db.get(m.BhavcopyFile, file_id)
    if not artifact:
        raise HTTPException(404, "Import not found")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["line", "isin", "code"])
    for error in artifact.errors or []:
        # Escape spreadsheet formula prefixes in externally supplied identifiers.
        writer.writerow(
            [
                ("'" + str(v)) if str(v).startswith(("=", "+", "-", "@")) else v
                for v in (error.get("line", ""), error.get("isin", ""), error.get("code", ""))
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="bhavcopy-errors.csv"'},
    )


@router.get("/prices/{company_id}")
async def private_prices(
    company_id: str, exchange: Literal["NSE", "BSE"], auth=Depends(admin), db=Depends(get_session)
):
    rows = (
        await db.scalars(
            select(m.DailyClose)
            .where(m.DailyClose.company_id == company_id, m.DailyClose.exchange == exchange)
            .order_by(m.DailyClose.trade_date.desc())
            .limit(1000)
        )
    ).all()
    return {"items": [record(row) for row in rows], "adjusted": False}

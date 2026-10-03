"""Anonymous, bounded click counters. Browser telemetry is best-effort, not unique visitors."""

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, select

from apps.api.cache import client
from apps.api.feedback_routes import insert_for
from apps.api.schemas import Input
from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.shared.config import settings

router = APIRouter()
Section = Literal["home", "ipos", "company", "tracker", "feedback", "information", "other"]
RETENTION = 400


def today_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class ClickBatch(Input):
    section: Section
    count: int = Field(ge=1, le=100, strict=True)


@router.post("/analytics/clicks", status_code=204)
async def clicks(body: ClickBatch, request: Request, db=Depends(get_session)):
    if request.headers.get("origin") != settings().public_origin:
        raise HTTPException(403, "Invalid request origin")
    # One short-lived global counter bounds public ingestion without retaining visitor IDs.
    try:
        count = await client.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            "analytics:ingest-limit",
        )
        if count > 3000:
            raise HTTPException(429, "Analytics busy")
    except HTTPException:
        raise
    except Exception:
        if settings().environment != "test":
            raise HTTPException(503, "Analytics unavailable") from None
    day = today_ist()
    statement = insert_for(db, m.ClickDaily).values(
        day=day, section=body.section, clicks=body.count
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["day", "section"],
            set_={"clicks": m.ClickDaily.clicks + statement.excluded.clicks},
        )
    )
    await db.execute(
        delete(m.ClickDaily).where(m.ClickDaily.day < day - timedelta(days=RETENTION - 1))
    )
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/admin/analytics")
async def analytics(response: Response, auth=Depends(admin), db=Depends(get_session)):
    today = today_ist()
    cutoff = today - timedelta(days=RETENTION - 1)
    # Also prune on reads so retention does not depend on continued public traffic.
    await db.execute(delete(m.ClickDaily).where(m.ClickDaily.day < cutoff))
    await db.commit()
    rows = (
        await db.scalars(
            select(m.ClickDaily)
            .where(m.ClickDaily.day >= cutoff, m.ClickDaily.day <= today)
            .order_by(m.ClickDaily.day)
        )
    ).all()
    week = today - timedelta(days=today.weekday())
    response.headers["Cache-Control"] = "no-store"
    return {
        "today": today.isoformat(),
        "timezone": "Asia/Kolkata",
        "retention_days": RETENTION,
        "totals": {
            "today": sum(r.clicks for r in rows if r.day == today),
            "week": sum(r.clicks for r in rows if r.day >= week),
            "month": sum(r.clicks for r in rows if r.day >= today.replace(day=1)),
        },
        "daily": [
            {"day": r.day.isoformat(), "section": r.section, "clicks": r.clicks} for r in rows
        ],
    }

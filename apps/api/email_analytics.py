"""Protected, aggregate-only email reporting. Cohorts use SES acceptance dates in IST."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, distinct, func, select

from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.ga4 import reports
from packages.shared.config import settings
from packages.shared.email_alerts import control, feature_enabled

router = APIRouter()
IST = ZoneInfo("Asia/Kolkata")


def bounds(start, end):
    today = m.now().astimezone(IST).date()
    end = end or today
    start = start or end - timedelta(days=29)
    if start > end or end > today or (end - start).days > 365:
        raise HTTPException(
            422,
            "Choose an ordered date range of at most 366 days, ending no later than today (IST).",
        )
    return (
        start,
        end,
        datetime.combine(start, time.min, IST).astimezone(timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, IST).astimezone(timezone.utc),
    )


def rate(numerator, denominator):
    return round(100 * numerator / denominator, 2) if denominator else None


def ist_day(db, column):
    return (
        func.date(func.timezone("Asia/Kolkata", column))
        if db.bind.dialect.name == "postgresql"
        else func.date(column, "+5 hours", "+30 minutes")
    )


@router.get("/admin/email-analytics", dependencies=[Depends(admin)])
async def analytics(
    start: date | None = None,
    end: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = "sessions",
    direction: str = "desc",
    db=Depends(get_session),
):
    start, end, lo, hi = bounds(start, end)
    if sort not in (
        "name",
        "delivered",
        "clickers",
        "ctr",
        "sessions",
        "unsubscribes",
        "send_date",
    ) or direction not in ("asc", "desc"):
        raise HTTPException(422, "Unsupported ordering")
    s = m.EmailSubscriber
    d = m.EmailDelivery
    total, active, new = (
        await db.execute(
            select(
                func.count(s.id),
                func.count(
                    case(
                        (
                            s.verified_at.is_not(None)
                            & s.unsubscribed_at.is_(None)
                            & s.suppressed_at.is_(None),
                            1,
                        )
                    )
                ),
                func.count(case(((s.created_at >= lo) & (s.created_at < hi), 1))),
            )
        )
    ).one()
    cohort = (d.kind == "ALERT", d.accepted_at >= lo, d.accepted_at < hi)
    delivered = d.delivered_at.is_not(None)
    counts = [
        func.count(d.id).label("sent"),
        func.count(case((delivered, 1))).label("delivered"),
        func.count(distinct(case((delivered & d.clicked_at.is_not(None), d.subscriber_id)))).label(
            "clickers"
        ),
        func.count(case((delivered & d.opened_at.is_not(None), 1))).label("opens"),
        func.count(
            distinct(case((delivered & d.unsubscribed_at.is_not(None), d.subscriber_id)))
        ).label("unsubscribes"),
    ]
    metrics = dict((await db.execute(select(*counts).where(*cohort))).mappings().one())
    metrics.update(
        total_subscribers=total,
        active_subscribers=active,
        new_subscribers=new,
        delivery_rate=rate(metrics["delivered"], metrics["sent"]),
        click_rate=rate(metrics["clickers"], metrics["delivered"]),
        open_rate=rate(metrics["opens"], metrics["delivered"])
        if settings().email_open_tracking_enabled
        else None,
        unsubscribe_rate=rate(metrics["unsubscribes"], metrics["delivered"]),
    )
    event_counts = (
        await db.execute(
            select(m.EmailClickEvent.classification, func.count())
            .where(m.EmailClickEvent.occurred_at >= lo, m.EmailClickEvent.occurred_at < hi)
            .group_by(m.EmailClickEvent.classification)
        )
    ).all()
    metrics["total_click_events"] = sum(n for _, n in event_counts)
    metrics["suspected_bot_events"] = sum(n for k, n in event_counts if k == "SUSPECTED_BOT")
    operations = dict(
        (
            await db.execute(
                select(d.status, func.count())
                .where(d.status.in_(["PENDING", "SENDING", "UNCERTAIN"]))
                .group_by(d.status)
            )
        ).all()
    )
    ga = await reports(start, end)
    traffic = {r["dimensions"][0]: r for r in ga.get("campaigns", [])}
    grouped = (
        select(m.EmailCampaign.ipo_id, *counts, func.min(d.accepted_at).label("send_date"))
        .join(m.EmailCampaign, m.EmailCampaign.id == d.campaign_id)
        .where(*cohort)
        .group_by(m.EmailCampaign.ipo_id)
        .subquery()
    )
    # Only aggregates enter memory; subscriber identities never leave SQL.
    rows = []
    for r in (
        await db.execute(
            select(grouped, m.Company.name, m.Company.slug, m.IPODate.listing_date)
            .join(m.IPO, m.IPO.id == grouped.c.ipo_id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .outerjoin(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
        )
    ).mappings():
        row = dict(r)
        t = traffic.get(row["slug"], {})
        row["ctr"] = rate(row["clickers"], row["delivered"])
        row["sessions"] = t.get("sessions", 0) if ga["status"] == "CONNECTED" else None
        row["engagement_seconds"] = (
            t.get("userEngagementDuration", 0) / t["sessions"] if t.get("sessions") else None
        )
        row["send_date"] = (
            row["send_date"].astimezone(IST).isoformat()
            if row["send_date"].tzinfo
            else row["send_date"].replace(tzinfo=timezone.utc).astimezone(IST).isoformat()
        )
        rows.append(row)
    available = [r for r in rows if r[sort] is not None]
    missing = [r for r in rows if r[sort] is None]
    available.sort(key=lambda r: (r[sort], r["ipo_id"]), reverse=direction == "desc")
    rows = available + missing
    first = (page - 1) * page_size
    daily_new = dict(
        (str(day), n)
        for day, n in (
            await db.execute(
                select(ist_day(db, s.created_at), func.count())
                .where(s.created_at >= lo, s.created_at < hi)
                .group_by(ist_day(db, s.created_at))
            )
        ).all()
    )
    daily_verified = dict(
        (str(day), n)
        for day, n in (
            await db.execute(
                select(ist_day(db, s.verified_at), func.count())
                .where(s.verified_at >= lo, s.verified_at < hi)
                .group_by(ist_day(db, s.verified_at))
            )
        ).all()
    )
    cumulative = await db.scalar(select(func.count()).select_from(s).where(s.verified_at < lo))
    daily_sessions = {r["dimensions"][0]: r["sessions"] for r in ga.get("daily", [])}
    growth = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        cumulative += daily_verified.get(str(day), 0)
        growth.append(
            {
                "day": str(day),
                "new": daily_new.get(str(day), 0),
                "verified": cumulative,
                "sessions": daily_sessions.get(day.strftime("%Y%m%d"), 0)
                if ga["status"] == "CONNECTED"
                else None,
            }
        )
    totals = ga.get("totals", {})
    summary = f"{new} new subscribers registered during this period."
    if ga["status"] == "CONNECTED":
        summary += f" Email-attributed traffic recorded {int(totals.get('sessions', 0))} sessions and {int(totals.get('engagedSessions', 0))} engaged sessions."
        best = max(rows, key=lambda r: r["sessions"] or 0, default=None)
        if best and best["sessions"]:
            summary += f" {best['name']} led traffic among IPOs emailed in this period."
    else:
        summary += (
            " Website traffic is unavailable; email clicks are not a substitute for sessions."
        )
    return {
        "start": start,
        "end": end,
        "timezone": "Asia/Kolkata",
        "metrics": metrics,
        "ga4": ga,
        "growth": growth,
        "rows": rows[first : first + page_size],
        "total_rows": len(rows),
        "page": page,
        "page_size": page_size,
        "summary": summary,
        "operations": operations,
        "enabled": settings().email_alerts_enabled
        and settings().ipo_email_sending_enabled
        and (await control(db)).sending_enabled
        and await feature_enabled(db),
        "sender": settings().email_from or None,
        "sending_configured": settings().email_alerts_enabled,
        "send_hour_ist": settings().email_send_hour_ist,
        "definitions": "Email metrics use messages accepted in the selected IST dates, with outcomes received to date. Clickers are distinct recipients with a confirmed delivery; suspected scanners are excluded, remaining clicks are unclassified. Traffic uses sessions occurring in the selected dates, including older emails. Growth counts first verification, including later unsubscribes. Unsubscribe counts are distinct recipients attributed to delivered emails.",
    }

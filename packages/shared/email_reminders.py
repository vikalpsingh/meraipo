"""Three Monday confirmation opportunities; manual batches share the same cap."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.email_alerts import delivery, feature_enabled

IST = ZoneInfo("Asia/Kolkata")


def reminder_week(created, now):
    created, now = utc(created).astimezone(IST), utc(now).astimezone(IST)
    first = created.replace(hour=9, minute=0, second=0, microsecond=0)
    first += timedelta(days=(7 - first.weekday()) % 7)
    if first <= created:
        first += timedelta(days=7)
    end = first + timedelta(weeks=3)
    if now < first or now >= end:
        return None
    return (first + timedelta(weeks=(now - first).days // 7)).date()


async def queue_reminders(db):
    if not await feature_enabled(db):
        return {"queued": 0, "message": "Email signup is disabled."}
    queued = 0
    # Row locks serialize manual and scheduled requests; unique weeks provide a second guard.
    rows = (
        await db.scalars(
            select(m.EmailSubscriber)
            .where(
                m.EmailSubscriber.verified_at.is_(None),
                m.EmailSubscriber.unsubscribed_at.is_(None),
                m.EmailSubscriber.suppressed_at.is_(None),
                m.EmailSubscriber.created_at >= m.now() - timedelta(days=28),
            )
            .order_by(m.EmailSubscriber.id)
            .with_for_update()
        )
    ).all()
    for sub in rows:
        week = reminder_week(sub.created_at, m.now())
        if not week:
            continue
        history = (
            await db.scalars(
                select(m.EmailDelivery)
                .where(m.EmailDelivery.subscriber_id == sub.id, m.EmailDelivery.kind == "VERIFY")
                .order_by(m.EmailDelivery.created_at.desc())
            )
        ).all()
        reminders = [r for r in history if r.reminder_week]
        if len(reminders) >= 3 or any(r.reminder_week == week for r in reminders):
            continue
        if any(utc(r.created_at) > m.now() - timedelta(days=1) for r in history):
            continue
        profile = next(
            (r.requested_profile_encrypted for r in history if r.requested_profile_encrypted), None
        )
        if not profile:
            continue  # Test-only recipients have not requested a subscription.
        row = delivery(sub.id)
        row.reminder_week = week
        row.requested_profile_encrypted = profile
        db.add(row)
        queued += 1
    await db.commit()
    return {
        "queued": queued,
        "message": f"Queued {queued} confirmation reminders. Active, opted-out, suppressed and ineligible users were skipped.",
    }

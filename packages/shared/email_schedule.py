"""Application reminders: database configuration, IST time and verified dates."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.config import settings

IST = ZoneInfo("Asia/Kolkata")


async def load(db):
    state = await db.get(m.EmailControl, "email")
    return {
        "mode": "opening",
        "time": f"{settings().email_send_hour_ist:02}:00",
        **(state.application_schedule or {} if state else {}),
    }


def in_window(config, now):
    hour, minute = map(int, config["time"].split(":"))
    elapsed = now.hour * 60 + now.minute - hour * 60 - minute
    return 0 <= elapsed < settings().email_catchup_hours * 60


def source_ready(ipo, dates, guide):
    """Imported issue dates do not require an unrelated editorial applicant guide."""
    if (ipo.quality or "").upper() in {"CONFLICT", "CONFLICTED", "INVALID", "REJECTED"}:
        return False
    if guide and guide.schedule_status == "CONFIRMED" and guide.verification_status == "VERIFIED":
        return True
    return bool(
        (ipo.source_provider or "").upper() in {"IPOALERTS", "IPOWEB", "NSE", "BSE"}
        and ipo.source_timestamp
        and m.now() - timedelta(hours=settings().email_ipo_max_age_hours)
        <= utc(ipo.source_timestamp)
        <= m.now()
        and dates
        and dates.open_date
        and dates.close_date
        and dates.open_date <= dates.close_date
    )


def occasion(ipo, dates, guide, day, mode):
    if not (
        dates
        and source_ready(ipo, dates, guide)
        and ipo.status.upper() in ("OPEN", "UPCOMING")
        and (ipo.raw_status or "").upper() not in ("CANCELLED", "POSTPONED", "WITHDRAWN")
    ):
        return None
    opening = mode in ("opening", "both") and dates.open_date == day
    closing = mode in ("closing", "both") and dates.close_date == day
    return (
        "opening_closing"
        if opening and closing
        else "opening"
        if opening
        else "closing"
        if closing
        else None
    )

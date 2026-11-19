"""Application reminders: database configuration, IST time and verified dates."""

from zoneinfo import ZoneInfo

from packages.database import models as m
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


def occasion(ipo, dates, guide, day, mode):
    if not (
        dates
        and guide
        and guide.schedule_status == "CONFIRMED"
        and guide.verification_status == "VERIFIED"
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

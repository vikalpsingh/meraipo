"""Single source of schedule timing for the five sequential operational jobs."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from packages.database import models as m
from packages.providers.bhavcopy import sources

EXCHANGE_JOBS = {
    f"sync-{kind}-{exchange.lower()}": (
        f"{exchange} · {'Daily closing prices' if kind=='prices' else 'Quarterly results'}",
        kind,
        exchange,
    )
    for kind in ("prices", "results")
    for exchange in ("NSE", "BSE")
}
SCHEDULED_JOBS = {**EXCHANGE_JOBS, "sync-ipos": ("IPO, subscription & GMP sync", "ipos", None)}
DEFAULT_TIMES = dict(
    zip(SCHEDULED_JOBS, ["19:00", "20:00", "21:00", "22:00", "23:00"], strict=True)
)


async def schedule_state(db, job, config):
    _, kind, exchange = SCHEDULED_JOBS[job]
    control = await db.get(m.SchedulerControl, job)
    parent = await db.get(m.SchedulerControl, f"sync-{kind}")
    paused = control.paused if control else bool(parent and parent.paused)
    times = control.schedule_times if control and control.schedule_times else [DEFAULT_TIMES[job]]
    if kind == "results":
        source = await db.get(m.ResultSource, exchange)
        enabled = source.enabled if source else True
        if not (control and control.schedule_times) and source:
            times = [source.schedule]
    elif kind == "prices":
        enabled = sources(config.bhavcopy_sources_json)[exchange].enabled
    else:
        enabled = True
    return {
        "times": sorted(times),
        "paused": paused,
        "source_enabled": enabled,
        "frequency": control.frequency if control else "daily",
        "weekday": control.weekday if control else 0,
    }


def is_due(state, at):
    local = at.astimezone(ZoneInfo("Asia/Kolkata"))
    if state["frequency"] == "hourly":
        return local.minute == int(state["times"][0].split(":")[1])
    if state["frequency"] == "weekly" and local.weekday() != state["weekday"]:
        return False
    return local.strftime("%H:%M") in state["times"]


def next_slot(times, at, frequency="daily", weekday=0):
    local = at.astimezone(ZoneInfo("Asia/Kolkata"))
    if frequency == "hourly":
        candidate = local.replace(minute=int(times[0].split(":")[1]), second=0, microsecond=0)
        return (candidate if candidate > local else candidate + timedelta(hours=1)).isoformat()
    for offset in range(8):
        day = local + timedelta(days=offset)
        if frequency == "weekly" and day.weekday() != weekday:
            continue
        for slot in sorted(times):
            hour, minute = map(int, slot.split(":"))
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > local:
                return candidate.isoformat()


def job_parameters(job, parameters=None):
    params = dict(parameters or {})
    if job in EXCHANGE_JOBS:
        _, kind, exchange = EXCHANGE_JOBS[job]
        params.update({"exchange": exchange} if kind == "prices" else {"exchanges": [exchange]})
    return params

"""Independent exchange job identities and the single source of schedule timing."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from packages.database import models as m
from packages.providers.bhavcopy import sources

EXCHANGE_JOBS = {
    f"sync-{kind}-{exchange.lower()}": (
        f"{exchange} · {'Daily closing prices' if kind == 'prices' else 'Quarterly results'}",
        kind,
        exchange,
    )
    for kind in ("prices", "results")
    for exchange in ("NSE", "BSE")
}


async def schedule_state(db, job, config):
    _, kind, exchange = EXCHANGE_JOBS[job]
    control = await db.get(m.SchedulerControl, job)
    parent = await db.get(m.SchedulerControl, f"sync-{kind}")
    paused = control.paused if control else bool(parent and parent.paused)
    if kind == "results":
        source = await db.get(m.ResultSource, exchange)
        times = [source.schedule if source else "19:30"]
        enabled = source.enabled if source else True
    else:
        times = (
            control.schedule_times
            if control and control.schedule_times
            else ["19:00", "20:00", "22:00"]
        )
        enabled = sources(config.bhavcopy_sources_json)[exchange].enabled
    return {"times": sorted(times), "paused": paused, "source_enabled": enabled}


def next_slot(times, at):
    local = at.astimezone(ZoneInfo("Asia/Kolkata"))
    for offset in (0, 1):
        for slot in sorted(times):
            hour, minute = map(int, slot.split(":"))
            candidate = (local + timedelta(days=offset)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate > local:
                return candidate.isoformat()


def job_parameters(job, parameters=None):
    params = dict(parameters or {})
    if job in EXCHANGE_JOBS:
        _, kind, exchange = EXCHANGE_JOBS[job]
        params.update({"exchange": exchange} if kind == "prices" else {"exchanges": [exchange]})
    return params

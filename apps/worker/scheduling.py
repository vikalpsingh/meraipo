"""Atomically claim due exchange slots before sending an ordered Celery chain."""

from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from packages.database import models as m
from packages.shared.job_schedules import EXCHANGE_JOBS, job_parameters, schedule_state


async def claim_due(db, config, at):
    if not config.market_scheduler_enabled or config.market_scheduler_driver != "celery":
        return []
    local = at.astimezone(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0)
    ids = []
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    for job in EXCHANGE_JOBS:
        state = await schedule_state(db, job, config)
        if (
            state["paused"]
            or not state["source_enabled"]
            or local.strftime("%H:%M") not in state["times"]
        ):
            continue
        statement = (
            insert(m.ImportRun)
            .values(
                key=f"scheduled:{job}:{local.isoformat()}",
                provider="market-feeds",
                job_name=job,
                trigger="scheduled",
                status="QUEUED",
                parameters=job_parameters(job),
            )
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(m.ImportRun.id)
        )
        run_id = await db.scalar(statement)
        if run_id:
            ids.append(run_id)
    await db.commit()
    return ids

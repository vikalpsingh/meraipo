"""Atomically claim due exchange slots before sending an ordered Celery chain."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from packages.database import models as m
from packages.shared.job_schedules import SCHEDULED_JOBS, is_due, job_parameters, schedule_state


async def claim_due(db, config, at):
    # Recover orphaned work even if nobody has the admin screen open.
    await db.execute(
        update(m.ImportRun)
        .where(
            m.ImportRun.job_name.is_not(None),
            m.ImportRun.status == "RUNNING",
            m.ImportRun.updated_at < m.now() - timedelta(minutes=10),
        )
        .execution_options(synchronize_session="fetch")
        .values(
            status="FAILED",
            error="WORKER_TIMEOUT: inspect worker health before retrying",
            finished_at=m.now(),
        )
    )
    await db.commit()
    if not config.market_scheduler_enabled or config.market_scheduler_driver != "celery":
        return []
    local = at.astimezone(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0)
    ids = []
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    for job in SCHEDULED_JOBS:
        state = await schedule_state(db, job, config)
        if state["paused"] or not state["source_enabled"] or not is_due(state, local):
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

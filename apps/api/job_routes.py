"""Admin-only run diagnostics and independent exchange schedule controls."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints
from sqlalchemy import func, select, update

from apps.api.repository import record
from apps.api.schemas import Input
from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.market import safe_url
from packages.shared.calculations import utc
from packages.shared.job_diagnostics import guidance
from packages.shared.job_schedules import EXCHANGE_JOBS, SCHEDULED_JOBS, next_slot, schedule_state
from packages.shared.market_config import load_market_settings

router = APIRouter(prefix="/admin/market")
Slot = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]


class ScheduleInput(Input):
    times: list[Slot] = Field(min_length=1, max_length=6)
    paused: bool
    frequency: Literal["hourly", "daily", "weekly"] = "daily"
    weekday: int = Field(0, ge=0, le=6)


def run_record(run):
    if not run:
        return None
    data = record(run)
    if run.status == "QUEUED" and (run.error or "").startswith("WAITING_FOR_PREVIOUS_JOB"):
        data["summary"] = (
            "Queued — waiting for the previous job to finish. Starts automatically when the data writer is available."
        )
    end = run.finished_at or m.now()
    data["duration_seconds"] = (
        max(0, round((utc(end) - utc(run.started_at)).total_seconds())) if run.started_at else None
    )
    counts = run.counters or {}
    if run.status == "SUCCESS":
        data["summary"] = (
            f"{counts.get('written', 0)} records published; {counts.get('unchanged', 0)} unchanged."
            if counts.get("written") or counts.get("unchanged")
            else "Scan completed; no matching new records to publish."
        )
    else:
        data["summary"] = (
            data.get("summary")
            or run.error
            or {
                "QUEUED": "Waiting for a worker.",
                "RUNNING": "Import in progress.",
                "SKIPPED": "No import performed.",
                "PARTIAL": "Some records failed; inspect diagnostics.",
                "FAILED": "Import failed; inspect diagnostics.",
            }.get(run.status, run.status)
        )
    return data


async def enrich_jobs(db, jobs, config):
    for job in jobs:
        name = job["name"]
        base = select(m.ImportRun).where(m.ImportRun.job_name == name)
        latest = await db.scalar(base.order_by(m.ImportRun.created_at.desc()).limit(1))
        success = await db.scalar(
            base.where(m.ImportRun.status == "SUCCESS")
            .order_by(m.ImportRun.finished_at.desc())
            .limit(1)
        )
        job["last"], job["last_success"] = run_record(latest), run_record(success)
        job["exchange"] = EXCHANGE_JOBS[name][2] if name in EXCHANGE_JOBS else None
        job["configurable"] = name in SCHEDULED_JOBS
        if name in SCHEDULED_JOBS:
            state = await schedule_state(db, name, config)
            job.update(state)
            job["schedule"] = ", ".join(state["times"]) + " " + state["frequency"]
            job["next_run"] = (
                next_slot(state["times"], m.now(), state["frequency"], state["weekday"])
                if config.market_scheduler_enabled
                and config.market_scheduler_driver == "celery"
                and not state["paused"]
                and state["source_enabled"]
                else None
            )
            job["schedule_note"] = (
                "Price imports check the exchange trading calendar."
                if SCHEDULED_JOBS[name][1] == "prices"
                else "Runs wait in sequence if an earlier job has not finished."
            )
    return jobs


@router.put("/{job}/schedule")
async def save_schedule(
    job: str, data: ScheduleInput, auth=Depends(admin), db=Depends(get_session)
):
    if job not in SCHEDULED_JOBS:
        raise HTTPException(404, "This job does not support exchange schedules")
    _, kind, exchange = SCHEDULED_JOBS[job]
    if (kind != "prices" or data.frequency != "daily") and len(data.times) != 1:
        raise HTTPException(422, "Choose one daily discovery time per exchange")
    if len(set(data.times)) != len(data.times):
        raise HTTPException(422, "Schedule times must be unique")
    control = await db.get(m.SchedulerControl, job)
    if not control:
        control = m.SchedulerControl(name=job)
        db.add(control)
    before = {
        "paused": control.paused,
        "times": control.schedule_times,
        "frequency": control.frequency,
        "weekday": control.weekday,
    }
    control.paused = data.paused
    control.frequency, control.weekday = data.frequency, data.weekday
    control.schedule_times = sorted(data.times)
    if kind == "results":
        source = await db.get(m.ResultSource, exchange)
        if not source:
            source = m.ResultSource(exchange=exchange, enabled=True, status="NOT_YET_RUN")
            db.add(source)
        before["times"] = [source.schedule] if source.schedule else []
        source.schedule = data.times[0]
    else:
        control.schedule_times = sorted(data.times)
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.schedule",
            entity_id=job,
            changes={"before": before, "after": data.model_dump()},
        )
    )
    await db.commit()
    return {"saved": True, **await schedule_state(db, job, await load_market_settings(db))}


@router.post("/runs/{run_id}/cancel")
async def cancel_queued(run_id: str, auth=Depends(admin), db=Depends(get_session)):
    cancelled = await db.scalar(
        update(m.ImportRun)
        .where(m.ImportRun.id == run_id, m.ImportRun.status == "QUEUED")
        .values(
            status="CANCELLED",
            error="Cancelled by administrator before execution",
            finished_at=m.now(),
        )
        .returning(m.ImportRun.id)
    )
    if not cancelled:
        raise HTTPException(409, "Only a queued run can be cancelled; refresh its status")
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.run.cancel",
            entity_id=run_id,
            changes={"status": "CANCELLED"},
        )
    )
    await db.commit()
    return {"status": "CANCELLED"}


@router.get("/runs")
async def history(
    job: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    auth=Depends(admin),
    db=Depends(get_session),
):
    criteria = [m.ImportRun.job_name.is_not(None)]
    if job:
        criteria.append(m.ImportRun.job_name == job)
    if status:
        criteria.append(m.ImportRun.status == status)
    total = await db.scalar(select(func.count()).select_from(m.ImportRun).where(*criteria))
    rows = (
        await db.scalars(
            select(m.ImportRun)
            .where(*criteria)
            .order_by(m.ImportRun.created_at.desc(), m.ImportRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [run_record(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/runs/{run_id}")
async def diagnostics(run_id: str, auth=Depends(admin), db=Depends(get_session)):
    run = await db.get(m.ImportRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    errors = (
        await db.scalars(
            select(m.JobError)
            .where(m.JobError.run_id == run_id)
            .order_by(m.JobError.created_at)
            .limit(200)
        )
    ).all()
    error_count = await db.scalar(
        select(func.count()).select_from(m.JobError).where(m.JobError.run_id == run_id)
    )
    files = (
        await db.scalars(
            select(m.BhavcopyFile)
            .where(m.BhavcopyFile.run_id == run_id)
            .order_by(m.BhavcopyFile.created_at)
        )
    ).all()
    return {
        "run": run_record(run),
        "errors": [dict(record(e), guidance=guidance(e.code)) for e in errors],
        "error_count": error_count,
        "files": [
            {
                "id": f.id,
                "exchange": f.exchange,
                "trade_date": str(f.trade_date),
                "status": f.status,
                "error": f.error,
                "guidance": guidance(f.error or f.status),
                "source_url": safe_url(f.source_url),
                "retry_at": f.retry_at,
                "counters": f.counters,
                "row_errors": (f.errors or [])[:25],
                "row_error_count": len(f.errors or []),
                "checksum": f.checksum,
            }
            for f in files
        ],
        "guidance": guidance(run.error),
    }

import secrets
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select, update

from apps.api.repository import record
from apps.api.schemas import Input
from apps.api.security import admin
from apps.worker.exchange_pipeline import PIPELINE_JOBS
from apps.worker.market import JOBS, create_run
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.exchanges import discovery_sources
from packages.providers.market import configuration
from packages.shared.config import settings
from packages.shared.market_freshness import freshness, next_scheduled

router = APIRouter()
ALL_JOBS = {**JOBS, **PIPELINE_JOBS}


class RunRequest(Input):
    retry_rejected: bool = False
    company_id: str | None = Field(None, max_length=36)
    from_date: date | None = None
    to_date: date | None = None
    confirm_backfill: bool = False


class PauseRequest(Input):
    paused: bool


async def dispatch(db, job, trigger, data):
    if job not in ALL_JOBS:
        raise HTTPException(404, "Unknown market job")
    if trigger == "scheduled" and not settings().market_scheduler_enabled:
        raise HTTPException(503, "Enable MARKET_SCHEDULER_ENABLED after completing setup")
    params = {}
    if data.retry_rejected:
        if not job.startswith(("publish-", "sync-")):
            raise HTTPException(422, "Retry rejected records with a publishing job")
        params["retry_rejected"] = True
    if data.company_id:
        company = await db.get(m.Company, data.company_id)
        if not company or company.is_demo:
            raise HTTPException(422, "Choose a tracked, non-demo company")
        params["company_id"] = data.company_id
    if job == "backfill":
        if not (data.confirm_backfill and data.company_id and data.from_date and data.to_date):
            raise HTTPException(422, "Confirm a company and bounded date range for backfill")
        if data.to_date > date.today() or not 0 <= (data.to_date - data.from_date).days <= 366:
            raise HTTPException(422, "Backfill one year at a time; future dates are not allowed")
        params.update({"from": data.from_date.isoformat(), "to": data.to_date.isoformat()})
    run = await create_run(db, job, trigger, params)
    try:
        from apps.worker.tasks import market_job

        market_job.delay(run.id)
    except Exception:
        run.status, run.error, run.finished_at = (
            "FAILED",
            "QUEUE_UNAVAILABLE: check Redis and worker",
            m.now(),
        )
        await db.commit()
        raise HTTPException(503, "Worker queue unavailable; failed attempt recorded") from None
    return {"id": run.id, "status": run.status}


@router.post("/internal/cron/{job}", status_code=202)
async def cron(job: str, request: Request, db=Depends(get_session)):
    secret = settings().cron_secret
    if len(secret) < 32 or not secrets.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + secret
    ):
        raise HTTPException(401, "Invalid cron authentication")
    if job == "backfill":
        raise HTTPException(404, "Manual job only")
    if settings().market_scheduler_driver != "vercel":
        raise HTTPException(409, "Celery owns scheduling; Vercel scheduling is disabled")
    return await dispatch(db, job, "scheduled", RunRequest())


@router.get("/admin/market")
async def overview(auth=Depends(admin), db=Depends(get_session)):
    # Recover visibility after a worker crash without pretending it completed.
    await db.execute(
        update(m.ImportRun)
        .where(
            m.ImportRun.job_name.is_not(None),
            m.ImportRun.status.in_(["RUNNING", "QUEUED"]),
            m.ImportRun.updated_at < m.now() - timedelta(minutes=10),
        )
        .values(
            status="FAILED",
            error="WORKER_TIMEOUT: retry after checking worker health",
            finished_at=m.now(),
        )
    )
    await db.commit()
    runs = (
        await db.scalars(
            select(m.ImportRun)
            .where(m.ImportRun.job_name.is_not(None))
            .order_by(m.ImportRun.created_at.desc())
            .limit(50)
        )
    ).all()
    controls = {c.name: c.paused for c in (await db.scalars(select(m.SchedulerControl))).all()}
    try:
        feeds = configuration(settings().market_feeds_json)
        native = discovery_sources(settings().exchange_sources_json)
        config_error = None
    except Exception:
        feeds, native, config_error = (
            {},
            [],
            "Invalid provider configuration; check MARKET_FEEDS_JSON and EXCHANGE_SOURCES_JSON",
        )
    providers = [
        {
            "kind": kind,
            "name": name,
            "authority": c.authority,
            "enabled": c.enabled,
            "credential_set": bool(c.token),
        }
        for kind, group in feeds.items()
        for name, c in group.items()
    ]
    if settings().exchange_direct_enabled:
        providers.extend(
            [
                {
                    "kind": kind,
                    "name": exchange,
                    "authority": exchange,
                    "enabled": True,
                    "credential_set": False,
                }
                for kind, exchange in (("ipos", "NSE"), ("prices", "NSE"), ("prices", "BSE"))
            ]
        )
        providers.extend(
            [
                {
                    "kind": s.kind,
                    "name": s.name,
                    "authority": s.exchange,
                    "enabled": True,
                    "credential_set": False,
                }
                for s in native
            ]
        )
    has_open = await db.scalar(
        select(m.IPO.id)
        .join(m.Company, m.Company.id == m.IPO.company_id)
        .where(m.IPO.status == "OPEN", m.Company.is_demo.is_(False))
        .limit(1)
    )
    for provider in providers:
        latest = await db.scalar(
            select(m.RawPayload)
            .where(
                m.RawPayload.provider == provider["name"],
                m.RawPayload.data_type == provider["kind"],
            )
            .order_by(m.RawPayload.created_at.desc())
            .limit(1)
        )
        failure = await db.scalar(
            select(m.JobError)
            .where(
                m.JobError.provider == provider["name"],
                m.JobError.item.like(provider["kind"] + "%"),
            )
            .order_by(m.JobError.created_at.desc())
            .limit(1)
        )
        from packages.shared.calculations import utc

        provider["last_fetched"] = utc(latest.created_at).isoformat() if latest else None
        provider["health"] = freshness(
            provider["kind"],
            latest.created_at if latest else None,
            m.now().astimezone(ZoneInfo("Asia/Kolkata")),
            active=provider["enabled"]
            and (provider["kind"] not in ("gmp", "subscriptions") or bool(has_open)),
            failed=bool(
                failure and (not latest or utc(failure.created_at) > utc(latest.created_at))
            ),
            holidays=settings().trading_holidays.split(","),
        )
    return {
        "driver": settings().market_scheduler_driver,
        "staging": {
            state: await db.scalar(
                select(func.count()).select_from(m.MarketStage).where(m.MarketStage.status == state)
            )
            for state in ("PENDING", "PUBLISHED", "REJECTED", "FALLBACK_NOT_NEEDED")
        },
        "enabled": settings().market_scheduler_enabled,
        "setup": [
            {
                "label": "Quarterly source mapping",
                "ready": any(s.kind == "results" and s.concepts for s in native)
                or any(c.enabled for c in feeds.get("results", {}).values()),
                "setting": "EXCHANGE_SOURCES_JSON · verified discovery fields and exact XBRL concept names",
            },
            {
                "label": "Cron authentication",
                "ready": settings().market_scheduler_driver == "celery"
                or len(settings().cron_secret) >= 32,
                "setting": "Docker: Celery scheduler; Vercel: shared CRON_SECRET",
            },
            {
                "label": "Provider feeds",
                "ready": settings().exchange_direct_enabled or any(p["enabled"] for p in providers),
                "setting": "EXCHANGE_DIRECT_ENABLED=true; review EXCHANGE_SOURCES_JSON for financial filings",
            },
            {
                "label": "Trading calendar",
                "ready": settings().trading_calendar_year == date.today().year,
                "setting": "TRADING_CALENDAR_YEAR and TRADING_HOLIDAYS",
            },
            {
                "label": "Scheduled execution",
                "ready": settings().market_scheduler_enabled,
                "setting": "MARKET_SCHEDULER_ENABLED=true after setup",
            },
        ],
        "configuration_error": config_error,
        "providers": providers,
        "jobs": [
            {
                "name": name,
                "label": values[0],
                "schedule": values[1],
                "paused": controls.get(name, False),
                "next_run": (
                    next_scheduled(
                        name,
                        m.now().astimezone(ZoneInfo("Asia/Kolkata")),
                        settings().trading_holidays.split(","),
                    )
                    if name.startswith("sync-")
                    and settings().market_scheduler_enabled
                    and not controls.get(name, False)
                    else None
                ),
                "last": next((record(r) for r in runs if r.job_name == name), None),
            }
            for name, values in ALL_JOBS.items()
        ],
        "runs": [record(r) for r in runs],
        "errors": [
            record(e)
            for e in (
                await db.scalars(
                    select(m.JobError).order_by(m.JobError.created_at.desc()).limit(30)
                )
            ).all()
        ],
    }


@router.post("/admin/market/{job}/run", status_code=202)
async def manual(job: str, data: RunRequest, auth=Depends(admin), db=Depends(get_session)):
    result = await dispatch(db, job, "manual", data)
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.run",
            entity_id=result["id"],
            changes={"job": job, "parameters": data.model_dump(mode="json")},
        )
    )
    await db.commit()
    return result


@router.post("/admin/market/{job}/pause")
async def pause(job: str, data: PauseRequest, auth=Depends(admin), db=Depends(get_session)):
    if job not in ALL_JOBS:
        raise HTTPException(404, "Unknown market job")
    control = await db.get(m.SchedulerControl, job)
    if not control:
        control = m.SchedulerControl(name=job)
        db.add(control)
    control.paused = data.paused
    db.add(
        m.Audit(
            admin_id=auth[0].id, action="market.pause", changes={"job": job, "paused": data.paused}
        )
    )
    await db.commit()
    return {"paused": data.paused}

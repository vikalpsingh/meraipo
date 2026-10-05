import asyncio
from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from redis import Redis
from sqlalchemy import select

from apps.worker.ingestion import ingest
from packages.database.models import ImportRun
from packages.database.session import Session, engine
from packages.providers.adapters import provider
from packages.shared.config import settings
from packages.shared.market_config import load_market_settings, market_settings_context

config = settings()
celery = Celery("meraipo", broker=config.redis_url, backend=config.redis_url)
celery.conf.update(
    timezone="Asia/Kolkata",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=240,
    task_time_limit=300,
    result_expires=86400,
    broker_connection_timeout=3,
    task_publish_retry=False,
    beat_schedule={
        name: {"task": "meraipo.scheduled_market", "schedule": schedule, "args": [name]}
        for name, schedule in {
            "sync-ipos": crontab(hour=23, minute=0),
            "sync-prices": crontab(hour="19,20,22", minute=0),
            "sync-results": crontab(minute="*"),
        }.items()
    },
)


@celery.task(name="meraipo.market", soft_time_limit=240, time_limit=300)
def market_job(run_id):
    from apps.worker.market import run_job

    async def execute_market():
        try:
            async with Session() as db:
                run = await db.get(ImportRun, run_id)
                if not run:
                    return {"status": "NOT_FOUND"}
                async with market_settings_context(db):
                    result = await run_job(db, run)
                return {"status": result.status}
        finally:
            await engine.dispose()
            from apps.api.cache import client

            await client.aclose()

    return asyncio.run(execute_market())


async def execute(kind, key):
    try:
        async with Session() as db:
            async with market_settings_context(db) as runtime:
                batch = await provider(runtime.provider_mode).fetch(kind)
                async with db.begin():
                    return await ingest(db, batch, key)
    finally:
        await engine.dispose()


async def failed(key, kind):
    try:
        async with Session() as db:
            runtime = await load_market_settings(db)
            run = await db.scalar(select(ImportRun).where(ImportRun.key == key))
            if not run:
                run = ImportRun(key=key, provider=runtime.provider_mode, status="FAILED")
                db.add(run)
            run.status = "FAILED"
            run.error = f"{kind} refresh exhausted retries; inspect worker logs using import key"
            await db.commit()
    finally:
        await engine.dispose()


@celery.task(bind=True, name="meraipo.refresh", max_retries=4)
def refresh(self, kind, import_key=None):
    key = import_key or f"{kind}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
    redis = Redis.from_url(config.redis_url)
    with redis.lock("job:" + key, timeout=330, blocking_timeout=1):
        try:
            with redis.lock("cache:writer", timeout=120, blocking_timeout=5):
                redis.set("cache:dirty", "1", ex=max(config.cache_ttl * 2, 300))
                result = asyncio.run(execute(kind, key))
                redis.incr("cache:generation")
                redis.delete("cache:dirty")
            return result
        except Exception as exc:
            if self.request.retries >= self.max_retries:
                asyncio.run(failed(key, kind))
                raise
            raise self.retry(
                exc=exc,
                countdown=min(30 * 2**self.request.retries, 900),
                args=(),
                kwargs={"kind": kind, "import_key": key},
            ) from exc


@celery.task(name="meraipo.scheduled_market")
def scheduled_market(job):
    from apps.worker.exchange_pipeline import PIPELINE_JOBS
    from apps.worker.market import create_run

    async def dispatch():
        try:
            async with Session() as db:
                runtime = await load_market_settings(db)
                if (
                    not runtime.market_scheduler_enabled
                    or runtime.market_scheduler_driver != "celery"
                    or job not in PIPELINE_JOBS
                ):
                    return {"status": "DISABLED"}
                if job == "sync-results":
                    from zoneinfo import ZoneInfo

                    from packages.database import models as m

                    local = datetime.now(ZoneInfo("Asia/Kolkata"))
                    sources = (await db.scalars(select(m.ResultSource))).all()
                    due = [
                        s.exchange
                        for s in sources
                        if s.enabled and s.schedule == local.strftime("%H:%M")
                    ]
                    if not sources and local.strftime("%H:%M") == "19:30":
                        due = ["BSE", "NSE"]
                    if not due:
                        return {"status": "NOT_DUE"}
                    prior = await db.scalar(
                        select(ImportRun.id).where(
                            ImportRun.job_name == job,
                            ImportRun.trigger == "scheduled",
                            ImportRun.created_at >= local.replace(second=0, microsecond=0),
                        )
                    )
                    if prior:
                        return {"status": "ALREADY_QUEUED"}
                async with market_settings_context(db):
                    run = await create_run(
                        db, job, "scheduled", {"exchanges": due} if job == "sync-results" else None
                    )
                    try:
                        market_job.delay(run.id)
                    except Exception:
                        run.status, run.error = "FAILED", "QUEUE_UNAVAILABLE"
                        await db.commit()
                        raise
                    return {"id": run.id}
        finally:
            await engine.dispose()

    return asyncio.run(dispatch())


celery.conf.beat_schedule["results-weekly-history"] = {
    "task": "meraipo.results_history",
    "schedule": crontab(hour=20, minute=30, day_of_week="0"),
}


@celery.task(name="meraipo.results_history")
def results_history():
    """Sequential company backfills share the normal job lease and failure isolation."""
    from datetime import timedelta

    from celery import chain

    from apps.worker.market import create_run, india_today
    from packages.database import models as m

    async def queue():
        try:
            async with Session() as db:
                runtime = await load_market_settings(db)
                if (
                    not runtime.market_scheduler_enabled
                    or runtime.market_scheduler_driver != "celery"
                ):
                    return {"status": "DISABLED"}
                companies = (
                    await db.scalars(
                        select(m.Company)
                        .join(m.Identifier)
                        .join(m.IPO)
                        .where(
                            m.Company.is_demo.is_(False),
                            m.Identifier.exchange.in_(["NSE", "BSE"]),
                            m.IPO.status == "LISTED",
                        )
                        .distinct()
                    )
                ).all()
                jobs = []
                today = india_today()
                for company in companies:
                    run = await create_run(
                        db,
                        "sync-results",
                        "reconciliation",
                        {
                            "company_id": company.id,
                            "from": (today - timedelta(days=1461)).isoformat(),
                            "to": today.isoformat(),
                            "history": True,
                        },
                    )
                    jobs.append(market_job.si(run.id))
                if jobs:
                    chain(*jobs).apply_async()
                return {"queued": len(jobs)}
        finally:
            await engine.dispose()

    return asyncio.run(queue())

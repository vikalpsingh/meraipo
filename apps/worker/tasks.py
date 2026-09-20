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
    beat_schedule=(
        {
            name: {"task": "meraipo.scheduled_market", "schedule": schedule, "args": [name]}
            for name, schedule in {
                "sync-ipos": crontab(hour=23, minute=0),
                "sync-prices": crontab(hour=23, minute=10, day_of_week="1-5"),
                "sync-results": crontab(hour=21, minute=0, day_of_week="5"),
            }.items()
        }
        if config.market_scheduler_enabled and config.market_scheduler_driver == "celery"
        else {}
    ),
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
                result = await run_job(db, run)
                return {"status": result.status}
        finally:
            await engine.dispose()
            from apps.api.cache import client

            await client.aclose()

    return asyncio.run(execute_market())


async def execute(kind, key):
    try:
        batch = await provider(config.provider_mode).fetch(kind)
        async with Session() as db:
            async with db.begin():
                return await ingest(db, batch, key)
    finally:
        await engine.dispose()


async def failed(key, kind):
    try:
        async with Session() as db:
            run = await db.scalar(select(ImportRun).where(ImportRun.key == key))
            if not run:
                run = ImportRun(key=key, provider=config.provider_mode, status="FAILED")
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

    if (
        not config.market_scheduler_enabled
        or config.market_scheduler_driver != "celery"
        or job not in PIPELINE_JOBS
    ):
        return {"status": "DISABLED"}

    async def dispatch():
        try:
            async with Session() as db:
                run = await create_run(db, job, "scheduled")
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

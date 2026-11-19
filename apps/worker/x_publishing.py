"""Separate X draft and durable publish tasks; no network retries for posts."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from apps.worker.tasks import celery
from packages.database import models as m
from packages.database.session import Session, engine
from packages.providers.x_api import XError
from packages.shared import x_publishing as service
from packages.shared.config import settings


async def tick(generate=False):
    if not settings().x_enabled:
        return {"status": "DISABLED"}
    try:
        async with service.operation_lock():
            async with Session() as db:
                await service.account(db)
                if generate:
                    for kind in service.DEFAULT_SCHEDULES:
                        rows = await service.generate_scheduled(db, kind)
                        if rows:
                            return {"status": "DRAFTED", "kind": kind}
                    return {"status": "NOT_DUE"}
                rows = (
                    await db.scalars(
                        select(m.XPost)
                        .where(m.XPost.status.in_(["QUEUED", "SENDING"]))
                        .order_by(m.XPost.created_at)
                        .limit(1)
                    )
                ).all()
                for row in rows:
                    if row.status == "SENDING":
                        if row.attempted_at and service.utc(row.attempted_at) < m.now() - timedelta(
                            minutes=3
                        ):
                            row.status, row.error_code = (
                                "UNCERTAIN",
                                "WORKER_INTERRUPTED_RECONCILE_ON_X",
                            )
                        continue
                    try:
                        await service.publish(db, row.id)
                    except XError as exc:
                        row.status, row.error_code = "FAILED", exc.code
                        row.api_status, row.request_id = exc.status, exc.request_id
                await db.commit()
                return {"status": "COMPLETE"}
    except XError as exc:
        return {"status": exc.code}


@celery.task(name="meraipo.x_daily", soft_time_limit=90, time_limit=110)
def daily():
    async def run():
        try:
            return await tick(True)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@celery.task(name="meraipo.x_outbox", soft_time_limit=90, time_limit=110)
def outbox():
    async def run():
        try:
            return await tick()
        finally:
            await engine.dispose()

    return asyncio.run(run())

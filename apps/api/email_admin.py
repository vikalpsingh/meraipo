"""Authenticated email operations; test mail targets only the signed-in administrator."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictBool
from sqlalchemy import func, select

from apps.api.feedback_routes import insert_for
from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.ses_readiness import config_hash, readiness
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_alerts import (
    control,
    delivery,
    normalized_email,
    token,
    tracked_url,
)
from packages.shared.email_policy import production_checks
from packages.shared.email_template import content
from packages.shared.market_config import encrypt_secret

router = APIRouter(prefix="/admin/email")


class Toggle(BaseModel):
    enabled: StrictBool


class TestRequest(BaseModel):
    ipo_id: str


def audit(db, auth, action, changes):
    db.add(m.Audit(admin_id=auth[0].id, action=action, changes=changes))


@router.get("/status")
async def status(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = False,
    auth=Depends(admin),
    db=Depends(get_session),
):
    state, checks = await production_checks(db, refresh)
    cutoff = m.now() - timedelta(days=days)
    counts = dict(
        (
            await db.execute(
                select(m.EmailDelivery.status, func.count())
                .where(m.EmailDelivery.kind == "ALERT", m.EmailDelivery.created_at >= cutoff)
                .group_by(m.EmailDelivery.status)
            )
        ).all()
    )
    counts["SCHEDULED"] = await db.scalar(
        select(func.count())
        .select_from(m.EmailDelivery)
        .where(m.EmailDelivery.kind == "ALERT", m.EmailDelivery.created_at >= cutoff)
    )
    counts["DELIVERED"] = await db.scalar(
        select(func.count())
        .select_from(m.EmailDelivery)
        .where(
            m.EmailDelivery.kind == "ALERT",
            m.EmailDelivery.created_at >= cutoff,
            m.EmailDelivery.delivered_at.is_not(None),
        )
    )
    counts["UNSUBSCRIBED"] = await db.scalar(
        select(func.count(func.distinct(m.EmailDelivery.subscriber_id))).where(
            m.EmailDelivery.kind == "ALERT", m.EmailDelivery.unsubscribed_at >= cutoff
        )
    )
    subscriber_counts = {}
    s = m.EmailSubscriber
    for label, predicate in {
        "active": s.verified_at.is_not(None)
        & s.unsubscribed_at.is_(None)
        & s.suppressed_at.is_(None),
        "pending": s.verified_at.is_(None)
        & s.suppressed_at.is_(None)
        & s.unsubscribed_at.is_(None),
        "unsubscribed": s.unsubscribed_at.is_not(None),
        "suppressed": s.suppressed_at.is_not(None),
    }.items():
        subscriber_counts[label] = await db.scalar(
            select(func.count()).select_from(s).where(predicate)
        )
    counts["ATTEMPTED"] = await db.scalar(
        select(func.count())
        .select_from(m.EmailDelivery)
        .where(
            m.EmailDelivery.kind == "ALERT",
            m.EmailDelivery.created_at >= cutoff,
            m.EmailDelivery.attempt_count > 0,
        )
    )
    counts["SES_ACCEPTED"] = await db.scalar(
        select(func.count())
        .select_from(m.EmailDelivery)
        .where(m.EmailDelivery.kind == "ALERT", m.EmailDelivery.accepted_at >= cutoff)
    )
    failures = (
        await db.scalars(
            select(m.EmailDelivery)
            .where(m.EmailDelivery.error_code.is_not(None))
            .order_by(m.EmailDelivery.updated_at.desc())
            .limit(25)
        )
    ).all()
    job = await db.scalar(
        select(m.EmailDispatchRun).order_by(m.EmailDispatchRun.created_at.desc()).limit(1)
    )
    success = await db.scalar(
        select(func.max(m.EmailDelivery.accepted_at)).where(m.EmailDelivery.kind == "ALERT")
    )
    test = await db.get(m.EmailDelivery, state.test_delivery_id) if state.test_delivery_id else None
    await db.commit()
    return {
        "sending_enabled": state.sending_enabled,
        "readiness": checks,
        "counts": counts,
        "subscribers": subscriber_counts,
        "scheduler_seen_at": state.scheduler_seen_at,
        "last_accepted_at": success,
        "test": {
            "id": test.id,
            "status": test.status,
            "delivered": bool(test.delivered_at),
            "received_confirmed": bool(state.test_received_at),
        }
        if test
        else None,
        "last_run": {
            "id": job.id,
            "status": job.status,
            "started_at": job.created_at,
            "finished_at": job.finished_at,
            "processed": job.processed,
            "error_code": job.error_code,
        }
        if job
        else None,
        "failures": [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "attempts": r.attempt_count,
                "code": r.error_code,
                "retry_at": r.retry_at,
                "eligible_retry": r.status in ("RETRY", "FAILED")
                and r.error_code == "SES_THROTTLED"
                and not r.accepted_at
                and r.attempt_count < settings().email_max_attempts,
            }
            for r in failures
        ],
    }


@router.put("/sending")
async def sending(data: Toggle, auth=Depends(admin), db=Depends(get_session)):
    if data.enabled:
        state, checks = await production_checks(db, refresh=True)
    else:
        state, checks = await control(db), {"ready": False}
    if data.enabled and not checks["ready"]:
        raise HTTPException(
            409,
            "Readiness checks must pass, including confirmed test delivery and scheduler heartbeat.",
        )
    before = state.sending_enabled
    state.sending_enabled = data.enabled
    audit(db, auth, "email.sending", {"before": before, "enabled": data.enabled})
    await db.commit()
    return {"enabled": state.sending_enabled}


@router.get("/preview/{ipo_id}")
async def preview(ipo_id: str, auth=Depends(admin), db=Depends(get_session)):
    ipo = await db.get(m.IPO, ipo_id)
    if not ipo:
        raise HTTPException(404, "IPO not found")
    company = await db.get(m.Company, ipo.company_id)
    origin = settings().public_origin.rstrip("/")
    return await content(
        db,
        ipo.id,
        tracked_url(origin + "/ipo/" + company.slug, company.slug),
        origin + "/email-alerts",
        test=True,
    )


@router.post("/test", status_code=202)
async def test_email(data: TestRequest, auth=Depends(admin), db=Depends(get_session)):
    aws = await readiness(True)
    if (
        not settings().public_origin.startswith("https://")
        or not aws.get("checks", {}).get("identity_verified")
        or not aws.get("checks", {}).get("sending_allowed")
    ):
        raise HTTPException(
            409, "Configure HTTPS and a verified, enabled SES sender before sending a test."
        )
    ipo = await db.get(m.IPO, data.ipo_id)
    if not ipo:
        raise HTTPException(404, "IPO not found")
    state = await control(db, lock=True)
    if state.test_delivery_id:
        previous = await db.get(m.EmailDelivery, state.test_delivery_id)
        if previous and utc(previous.created_at) > m.now() - timedelta(minutes=5):
            raise HTTPException(429, "Wait five minutes between test emails.")
    address = normalized_email(auth[0].email)
    identity = token(address, "email")
    await db.execute(
        insert_for(db, m.EmailSubscriber)
        .values(email_hash=identity, email_encrypted=encrypt_secret(address), consent_at=m.now())
        .on_conflict_do_nothing(index_elements=["email_hash"])
    )
    subscriber = await db.scalar(
        select(m.EmailSubscriber).where(m.EmailSubscriber.email_hash == identity)
    )
    if subscriber.suppressed_at:
        raise HTTPException(409, "This administrator address is suppressed.")
    campaign = m.EmailCampaign(
        ipo_id=ipo.id,
        kind="test_" + token(str(m.now()), "test")[:20],
        scheduled_date=m.now().astimezone(ZoneInfo("Asia/Kolkata")).date(),
    )
    db.add(campaign)
    await db.flush()
    row = delivery(subscriber.id, campaign.id)
    row.kind = "TEST"
    db.add(row)
    await db.flush()
    state.test_delivery_id = row.id
    state.test_received_at = None
    state.test_config_hash = config_hash()
    audit(db, auth, "email.test.requested", {"delivery_id": row.id, "ipo_id": ipo.id})
    await db.commit()
    return {
        "message": "TEST queued for your administrator email. In SES sandbox, that recipient must also be verified.",
        "id": row.id,
    }


@router.post("/test/{delivery_id}/received")
async def received(delivery_id: str, auth=Depends(admin), db=Depends(get_session)):
    state = await control(db, lock=True)
    row = await db.get(m.EmailDelivery, delivery_id)
    sub = await db.get(m.EmailSubscriber, row.subscriber_id) if row else None
    if (
        not row
        or state.test_delivery_id != row.id
        or row.kind != "TEST"
        or not row.delivered_at
        or sub.email_hash != token(normalized_email(auth[0].email), "email")
    ):
        raise HTTPException(
            409,
            "Only the test recipient can confirm the current test after signed delivery feedback.",
        )
    state.test_received_at = m.now()
    audit(db, auth, "email.test.received", {"delivery_id": row.id})
    await db.commit()
    return {"message": "Test inbox receipt confirmed."}


@router.post("/retry/{delivery_id}")
async def retry(delivery_id: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.EmailDelivery, delivery_id, with_for_update=True)
    if (
        not row
        or row.status not in ("RETRY", "FAILED")
        or row.error_code != "SES_THROTTLED"
        or row.accepted_at
        or row.attempt_count >= settings().email_max_attempts
    ):
        raise HTTPException(
            409,
            "Only explicitly throttled, unaccepted deliveries within their retry budget are eligible.",
        )
    row.status = "RETRY"
    row.retry_at = max(
        utc(row.retry_at) if row.retry_at else m.now(),
        m.now() + timedelta(seconds=min(3600, 30 * 2**row.attempt_count)),
    )
    # Preserve exponential backoff; admin retry never bypasses the rate limit.
    audit(db, auth, "email.retry.reviewed", {"delivery_id": row.id})
    await db.commit()
    return {
        "message": "Eligible retry remains scheduled with backoff; the worker rechecks consent and listing dates.",
        "retry_at": row.retry_at,
    }

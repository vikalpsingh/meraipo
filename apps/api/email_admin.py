"""Authenticated email operations; test mail targets only the signed-in administrator."""

import json
from datetime import timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import delete, func, select, update

from apps.api.feedback_routes import insert_for
from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.ses_readiness import config_hash, readiness
from packages.shared import email_schedule
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_alerts import (
    control,
    delivery,
    normalized_email,
    token,
    tracked_url,
)
from packages.shared.email_digest import build_payloads
from packages.shared.email_policy import production_checks
from packages.shared.email_preferences import BANDS
from packages.shared.email_template import content
from packages.shared.market_config import decrypt_secret, encrypt_secret

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
            .where(m.EmailDelivery.error_code.is_not(None), m.EmailDelivery.updated_at >= cutoff)
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
        "application_schedule": await email_schedule.load(db),
        "send_hour_ist": settings().email_send_hour_ist,
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
                "created_at": r.created_at,
                "updated_at": r.updated_at,
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


class ApplicationSchedule(BaseModel):
    mode: Literal["opening", "closing", "both"]
    time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


@router.put("/application-schedule")
async def application_schedule(
    data: ApplicationSchedule, auth=Depends(admin), db=Depends(get_session)
):
    state = await control(db, lock=True)
    state.application_schedule = data.model_dump()
    audit(db, auth, "email.application_schedule", data.model_dump())
    await db.commit()
    return {
        "message": "Application schedule saved in IST. Applies to the next daily snapshot; existing queued digests are unchanged."
    }


@router.post("/application-test", status_code=202)
async def application_test(auth=Depends(admin), db=Depends(get_session)):
    await require_test_sender()
    await control(db, lock=True)
    recent = await db.scalar(
        select(m.EmailCampaign.id)
        .where(
            m.EmailCampaign.kind.startswith("application_test:"),
            m.EmailCampaign.created_at > m.now() - timedelta(minutes=5),
        )
        .limit(1)
    )
    if recent:
        raise HTTPException(429, "Wait five minutes between application digest tests.")
    today = m.now().astimezone(email_schedule.IST)
    listings = (
        await db.execute(
            select(m.IPO, m.IPODate, m.ApplicantGuide)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .join(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
            .where(
                m.Company.is_demo.is_(False),
                (m.IPODate.open_date == today.date()) | (m.IPODate.close_date == today.date()),
            )
        )
    ).all()
    config = await email_schedule.load(db)
    payload = (await build_payloads(db, listings, today, config)).get("white")
    if not payload or not payload["ipo_ids"]:
        raise HTTPException(
            409,
            "No verified IPO matches today's selected opening/closing schedule. Check dates and confirmed applicant guides. Nothing was sent.",
        )
    payload["subject"] = "TEST | MeraIPO application reminders"
    payload["text"] = (
        "TEST — All IPOs preference; subscriber settings unchanged.\n" + payload["text"]
    )
    payload["html"] = payload["html"].replace(
        "IPO application reminders", "IPO application reminders · TEST"
    )
    sub = await test_recipient(db, "meshanti.singh@gmail.com")
    campaign = m.EmailCampaign(
        ipo_id=payload["ipo_ids"][0],
        kind="application_test:" + uuid4().hex[:8],
        scheduled_date=today.date(),
        digest_payload=payload,
    )
    db.add(campaign)
    await db.flush()
    row = delivery(sub.id, campaign.id)
    row.kind = "TEST"
    db.add(row)
    audit(
        db,
        auth,
        "email.application_test",
        {"delivery_id": row.id, "ipo_count": len(payload["ipo_ids"]), "mode": config["mode"]},
    )
    await db.commit()
    return {
        "message": f"Queued one TEST email containing {len(payload['ipo_ids'])} IPO(s) to meshanti.singh@gmail.com. Delivery ID: {row.id}",
        "id": row.id,
    }


@router.get("/application-test/{key}")
async def application_test_status(key: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.EmailDelivery, key)
    campaign = await db.get(m.EmailCampaign, row.campaign_id) if row and row.campaign_id else None
    if (
        not row
        or row.kind != "TEST"
        or not campaign
        or not campaign.kind.startswith("application_test:")
    ):
        raise HTTPException(404, "Application test not found")
    return {
        "id": row.id,
        "status": row.status,
        "accepted_at": row.accepted_at,
        "delivered_at": row.delivered_at,
        "error_code": row.error_code,
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


class CategoryTestRequest(TestRequest):
    email: str = Field(max_length=254)
    categories: list[str] = Field(min_length=1, max_length=4)


async def require_test_sender():
    if len(settings().email_token_secret.get_secret_value()) < 32:
        raise HTTPException(409, "Configure the email token secret before testing.")
    aws = await readiness(True)
    if (
        not settings().public_origin.startswith("https://")
        or not aws.get("checks", {}).get("identity_verified")
        or not aws.get("checks", {}).get("sending_allowed")
    ):
        raise HTTPException(
            409, "Configure HTTPS and a verified, enabled SES sender before sending a test."
        )


async def test_recipient(db, address):
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
        raise HTTPException(409, "This recipient address is suppressed.")
    return subscriber


@router.post("/category-tests", status_code=202)
async def category_tests(data: CategoryTestRequest, auth=Depends(admin), db=Depends(get_session)):
    if len(set(data.categories)) != len(data.categories) or any(
        c not in BANDS for c in data.categories
    ):
        raise HTTPException(422, "Choose each email category at most once.")
    try:
        address = normalized_email(data.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await require_test_sender()
    if not await db.get(m.IPO, data.ipo_id):
        raise HTTPException(404, "IPO not found")
    await control(db, lock=True)
    recent = await db.scalar(
        select(m.EmailCampaign.id)
        .where(
            m.EmailCampaign.kind.startswith("category:"),
            m.EmailCampaign.created_at > m.now() - timedelta(minutes=5),
        )
        .limit(1)
    )
    if recent:
        raise HTTPException(429, "Wait five minutes between category test batches.")
    sub = await test_recipient(db, address)
    ids = []
    for category in data.categories:
        campaign = m.EmailCampaign(
            ipo_id=data.ipo_id,
            kind=f"category:{category}:{uuid4().hex[:8]}",
            scheduled_date=m.now().astimezone(ZoneInfo("Asia/Kolkata")).date(),
        )
        db.add(campaign)
        await db.flush()
        row = delivery(sub.id, campaign.id)
        row.kind = "TEST"
        db.add(row)
        ids.append(row.id)
    audit(
        db,
        auth,
        "email.category_test",
        {"deliveries": ids, "categories": data.categories, "ipo_id": data.ipo_id},
    )
    await db.commit()
    return {"message": f"Queued {len(ids)} category test email(s).", "ids": ids}


@router.post("/test", status_code=202)
async def test_email(data: TestRequest, auth=Depends(admin), db=Depends(get_session)):
    await require_test_sender()
    ipo = await db.get(m.IPO, data.ipo_id)
    if not ipo:
        raise HTTPException(404, "IPO not found")
    state = await control(db, lock=True)
    if state.test_delivery_id:
        previous = await db.get(m.EmailDelivery, state.test_delivery_id)
        if previous and utc(previous.created_at) > m.now() - timedelta(minutes=5):
            raise HTTPException(429, "Wait five minutes between test emails.")
    address = normalized_email(auth[0].email)
    subscriber = await test_recipient(db, address)
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


@router.get("/subscribers")
async def subscribers(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth=Depends(admin),
    db=Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    s = m.EmailSubscriber
    registered = (
        s.contact_encrypted.is_not(None)
        | select(m.EmailDelivery.id)
        .where(m.EmailDelivery.subscriber_id == s.id, m.EmailDelivery.kind == "VERIFY")
        .exists()
    )
    counts = {}
    for label, condition in {
        "total": registered,
        "active": registered
        & s.verified_at.is_not(None)
        & s.unsubscribed_at.is_(None)
        & s.suppressed_at.is_(None),
        "pending": registered
        & s.verified_at.is_(None)
        & s.unsubscribed_at.is_(None)
        & s.suppressed_at.is_(None),
        "unsubscribed": registered & s.unsubscribed_at.is_not(None) & s.suppressed_at.is_(None),
        "suppressed": registered & s.suppressed_at.is_not(None),
    }.items():
        counts[label] = await db.scalar(select(func.count()).select_from(s).where(condition))
    pages = max(1, (counts["total"] + page_size - 1) // page_size)
    page = min(page, pages)
    rows = (
        await db.scalars(
            select(s)
            .where(registered)
            .order_by(s.created_at.desc(), s.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    pending = {}
    if rows:
        deliveries = (
            await db.scalars(
                select(m.EmailDelivery)
                .where(
                    m.EmailDelivery.subscriber_id.in_([r.id for r in rows]),
                    m.EmailDelivery.kind == "VERIFY",
                    m.EmailDelivery.requested_profile_encrypted.is_not(None),
                )
                .order_by(m.EmailDelivery.created_at.desc(), m.EmailDelivery.id)
            )
        ).all()
        for delivery in deliveries:
            pending.setdefault(delivery.subscriber_id, delivery.requested_profile_encrypted)
    items = []
    for row in rows:
        encrypted = row.contact_encrypted or pending.get(row.id)
        profile = json.loads(decrypt_secret(encrypted)) if encrypted else {}
        items.append(
            dict(
                id=row.id,
                first_name=profile.get("first_name"),
                last_name=profile.get("last_name"),
                broker=profile.get("broker", "other"),
                email=decrypt_secret(row.email_encrypted),
                gmp_band=row.gmp_band or profile.get("gmp_band"),
                status="Suppressed"
                if row.suppressed_at
                else "Unsubscribed"
                if row.unsubscribed_at
                else "Active"
                if row.verified_at
                else "Pending confirmation",
                created_at=row.created_at,
            )
        )
    return dict(items=items, counts=counts, page=page, pages=pages, page_size=page_size)


@router.post("/subscribers/remind")
async def remind_subscribers(auth=Depends(admin), db=Depends(get_session)):
    from packages.shared.email_reminders import queue_reminders

    await require_test_sender()
    result = await queue_reminders(db)
    audit(db, auth, "email.confirmation_reminders", {"queued": result["queued"]})
    await db.commit()
    return result


class SubscriberEdit(BaseModel):
    first_name: str
    last_name: str
    gmp_band: str
    broker: str = "other"


@router.put("/subscribers/{subscriber_id}")
async def edit_subscriber(
    subscriber_id: str, data: SubscriberEdit, auth=Depends(admin), db=Depends(get_session)
):
    from packages.shared.email_preferences import validate_profile

    row = await db.get(m.EmailSubscriber, subscriber_id, with_for_update=True)
    if not row:
        raise HTTPException(404, "Subscriber not found")
    try:
        profile = validate_profile(data.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Preserve optional contact data and confirmation/suppression state.
    previous = json.loads(decrypt_secret(row.contact_encrypted)) if row.contact_encrypted else {}
    profile["phone"] = previous.get("phone")
    if row.verified_at:
        row.contact_encrypted = encrypt_secret(
            json.dumps({k: v for k, v in profile.items() if k != "gmp_band"})
        )
        row.gmp_band = profile["gmp_band"]
    await db.execute(
        update(m.EmailDelivery)
        .where(
            m.EmailDelivery.subscriber_id == row.id,
            m.EmailDelivery.kind == "VERIFY",
            m.EmailDelivery.status != "CONFIRMED",
        )
        .values(requested_profile_encrypted=encrypt_secret(json.dumps(profile)))
    )
    audit(db, auth, "email.subscriber.edit", {"subscriber_id": row.id})
    await db.commit()
    return {"message": "Subscriber updated. Confirmation and suppression status were preserved."}


@router.delete("/subscribers/{subscriber_id}")
async def delete_subscriber(subscriber_id: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.EmailSubscriber, subscriber_id, with_for_update=True)
    if not row:
        raise HTTPException(404, "Subscriber not found")
    deliveries = select(m.EmailDelivery.id).where(m.EmailDelivery.subscriber_id == row.id)
    if await db.scalar(
        select(m.EmailDelivery.id)
        .where(
            m.EmailDelivery.subscriber_id == row.id,
            m.EmailDelivery.status.in_(["SENDING", "UNCERTAIN"]),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "A delivery is in progress or uncertain. Reconcile it before deleting."
        )
    await db.execute(
        update(m.EmailControl)
        .where(m.EmailControl.test_delivery_id.in_(deliveries))
        .values(test_delivery_id=None, test_received_at=None, test_config_hash=None)
    )
    await db.execute(delete(m.EmailClickEvent).where(m.EmailClickEvent.delivery_id.in_(deliveries)))
    await db.execute(
        delete(m.EmailDeliveryEvent).where(m.EmailDeliveryEvent.delivery_id.in_(deliveries))
    )
    await db.execute(delete(m.EmailReservation).where(m.EmailReservation.subscriber_id == row.id))
    await db.execute(delete(m.EmailDelivery).where(m.EmailDelivery.subscriber_id == row.id))
    await db.delete(row)
    audit(db, auth, "email.subscriber.delete", {"subscriber_id": subscriber_id})
    await db.commit()
    return {"message": "Subscriber and associated delivery records deleted."}

"""Double opt-in, opaque click redirects and authenticated SES notifications."""

import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from apps.api.cache import client
from apps.api.feedback_routes import insert_for
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.ses_events import verify_sns
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_alerts import (
    active,
    classify_click,
    delivery,
    digest,
    feature_enabled,
    normalized_email,
    token,
    token_expired,
    tracked_url,
)
from packages.shared.market_config import encrypt_secret

router = APIRouter()


async def throttle(key, limit, seconds):
    try:
        count = await client.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
            1,
            "email-limit:" + key,
            seconds,
        )
        if count > limit:
            raise HTTPException(429, "Please try again later.")
    except HTTPException:
        raise
    except Exception:
        if settings().environment != "test":
            raise HTTPException(503, "Email service is temporarily unavailable.") from None


def enabled():
    c = settings()
    if (
        not c.email_alerts_enabled
        or not c.email_from
        or len(c.email_token_secret.get_secret_value()) < 32
    ):
        raise HTTPException(503, "Email alerts are not configured yet.")


def origin(request):
    if request.headers.get("origin") != settings().public_origin:
        raise HTTPException(403, "Invalid request origin")


@router.post("/ipo-alerts/subscribe", status_code=202)
async def subscribe(request: Request, db=Depends(get_session)):
    enabled()
    if not await feature_enabled(db):
        raise HTTPException(404, "Email alerts are currently unavailable.")
    origin(request)
    try:
        body = await request.json()
        if body.get("consent") is not True:
            raise ValueError("Consent is required")
        email = normalized_email(body.get("email", ""))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "A valid email and consent are required.") from None
    identity = token(email, "email")
    await throttle("address:" + identity, 3, 86400)
    # The API sees the reverse proxy, not a trustworthy visitor IP. Per-IP limits
    # belong at the gateway; this ceiling protects the shared email outbox.
    await throttle("signup-global", 1000, 3600)
    statement = (
        insert_for(db, m.EmailSubscriber)
        .values(email_hash=identity, email_encrypted=encrypt_secret(email), consent_at=m.now())
        .on_conflict_do_nothing(index_elements=["email_hash"])
    )
    await db.execute(statement)
    subscriber = await db.scalar(
        select(m.EmailSubscriber).where(m.EmailSubscriber.email_hash == identity).with_for_update()
    )
    recent = await db.scalar(
        select(m.EmailDelivery.id)
        .where(
            m.EmailDelivery.subscriber_id == subscriber.id,
            m.EmailDelivery.kind == "VERIFY",
            m.EmailDelivery.created_at > m.now() - timedelta(hours=24),
        )
        .limit(1)
    )
    if not active(subscriber) and not subscriber.suppressed_at and not recent:
        db.add(delivery(subscriber.id))
    await db.commit()
    # Same response for new, existing and suppressed addresses (no enumeration).
    return JSONResponse(
        {
            "message": "If eligible, you will receive a confirmation email. Check your inbox and spam folder."
        },
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )


async def action_row(db, value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise HTTPException(400, "Invalid or expired link")
    row = await db.scalar(
        select(m.EmailDelivery)
        .where(m.EmailDelivery.action_hash == digest(value))
        .with_for_update()
    )
    if not row or (
        row.kind != "VERIFY"
        and utc(row.created_at) < m.now() - timedelta(days=settings().email_unsubscribe_days)
    ):
        raise HTTPException(400, "Invalid or expired link")
    return row


@router.post("/ipo-alerts/confirm")
async def confirm(request: Request, db=Depends(get_session)):
    origin(request)
    body = await request.json()
    row = await action_row(db, body.get("token"))
    if row.kind != "VERIFY" or token_expired(row):
        raise HTTPException(400, "Invalid or expired link")
    subscriber = await db.get(m.EmailSubscriber, row.subscriber_id, with_for_update=True)
    if subscriber.suppressed_at:
        raise HTTPException(400, "This address cannot receive alerts.")
    # A consumed confirmation cannot reactivate a later unsubscribe.
    if row.status != "CONFIRMED":
        subscriber.verified_at = subscriber.verified_at or m.now()
        subscriber.unsubscribed_at = None
        subscriber.consent_at = m.now()
        row.status = "CONFIRMED"
    await db.commit()
    return {"message": "Your email is confirmed. You are subscribed to pre-listing IPO alerts."}


async def do_unsubscribe(db, value):
    row = await action_row(db, value)
    subscriber = await db.get(m.EmailSubscriber, row.subscriber_id, with_for_update=True)
    subscriber.unsubscribed_at = subscriber.unsubscribed_at or m.now()
    row.unsubscribed_at = row.unsubscribed_at or m.now()
    await db.commit()
    return {"message": "You are unsubscribed from MeraIPO email alerts."}


@router.post("/ipo-alerts/unsubscribe")
async def unsubscribe(request: Request, db=Depends(get_session)):
    origin(request)
    body = await request.json()
    return await do_unsubscribe(db, body.get("token"))


@router.get("/ipo-alerts/unsubscribe/{value}")
async def unsubscribe_landing(value: str):
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise HTTPException(400, "Invalid link")
    return RedirectResponse(
        settings().public_origin.rstrip("/") + "/email-alerts/unsubscribe#" + value,
        status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/ipo-alerts/unsubscribe/{value}")
async def one_click(value: str, request: Request, db=Depends(get_session)):
    if await request.body() != b"List-Unsubscribe=One-Click":
        raise HTTPException(400, "Invalid one-click request")
    return await do_unsubscribe(db, value)


@router.get("/ipo-alerts/click/{value}")
async def click(value: str, request: Request, db=Depends(get_session)):
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise HTTPException(404, "Link not found")
    result = (
        await db.execute(
            select(m.EmailDelivery, m.EmailCampaign, m.Company)
            .join(m.EmailCampaign, m.EmailCampaign.id == m.EmailDelivery.campaign_id)
            .join(m.IPO, m.IPO.id == m.EmailCampaign.ipo_id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .where(m.EmailDelivery.click_hash == digest(value))
        )
    ).first()
    if not result:
        raise HTTPException(404, "Link not found")
    row, campaign, company = result
    classification = classify_click(
        request.headers.get("user-agent", ""),
        request.headers.get("purpose", "") + " " + request.headers.get("sec-purpose", ""),
    )
    target = tracked_url(
        settings().public_origin.rstrip("/") + "/ipo/" + company.slug, company.slug, campaign.kind
    )
    # Rate-limit storage, not the redirect; prefetch storms must not break valid links.
    try:
        await throttle("click:" + row.id, 100, 3600)
        db.add(
            m.EmailClickEvent(
                delivery_id=row.id,
                ipo_id=campaign.ipo_id,
                campaign_id=campaign.id,
                occurred_at=m.now(),
                classification=classification,
            )
        )
        if classification == "UNCLASSIFIED" and not row.clicked_at:
            row.clicked_at = m.now()
        await db.commit()
    except (HTTPException, SQLAlchemyError):
        await db.rollback()
    return RedirectResponse(
        target,
        status_code=302,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


async def ingest_event(db, provider_id, event):
    mail = event.get("mail", {})
    if not isinstance(mail.get("messageId"), str) or not mail["messageId"]:
        raise HTTPException(400, "Missing message identity")
    row = await db.scalar(
        select(m.EmailDelivery)
        .where(m.EmailDelivery.message_id == mail.get("messageId"))
        .with_for_update()
    )
    if not row:
        keys = mail.get("tags", {}).get("delivery_id", [])
        if keys:
            row = await db.get(m.EmailDelivery, keys[0], with_for_update=True)
    if not row:
        raise HTTPException(503, "Delivery record not available yet")
    if row.message_id and row.message_id != mail["messageId"]:
        raise HTTPException(409, "SES message does not match the reserved delivery")
    kind = event.get("eventType") or event.get("notificationType")
    kind = {
        "SEND": "Send",
        "DELIVERY": "Delivery",
        "BOUNCE": "Bounce",
        "COMPLAINT": "Complaint",
        "REJECT": "Reject",
        "DELIVERY_DELAY": "DeliveryDelay",
    }.get(kind, kind)
    if kind not in ("Delivery", "Bounce", "Complaint", "Open", "Send", "Reject", "DeliveryDelay"):
        return
    detail = event.get(kind[0].lower() + kind[1:], {})
    try:
        stamp = datetime.fromisoformat(
            (detail.get("timestamp") or mail["timestamp"]).replace("Z", "+00:00")
        )
        accepted = datetime.fromisoformat(mail["timestamp"].replace("Z", "+00:00"))
        if (
            not stamp.tzinfo
            or not accepted.tzinfo
            or max(stamp, accepted) > m.now() + timedelta(minutes=5)
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid event timestamp") from None
    inserted = await db.execute(
        insert_for(db, m.EmailDeliveryEvent)
        .values(provider_event_id=provider_id, delivery_id=row.id, status=kind, occurred_at=stamp)
        .on_conflict_do_nothing(index_elements=["provider_event_id"])
    )
    if inserted.rowcount != 1:
        return
    row.message_id = row.message_id or mail.get("messageId")
    row.accepted_at = row.accepted_at or accepted
    if kind == "Delivery":
        row.delivered_at = row.delivered_at or stamp
    if kind == "Open" and settings().email_open_tracking_enabled:
        row.opened_at = row.opened_at or stamp
    if kind == "Complaint" or (kind == "Bounce" and detail.get("bounceType") != "Transient"):
        subscriber = await db.get(m.EmailSubscriber, row.subscriber_id, with_for_update=True)
        subscriber.suppressed_at = subscriber.suppressed_at or stamp
    states = {
        "Send": "ACCEPTED",
        "Delivery": "DELIVERED",
        "DeliveryDelay": "DELAYED",
        "Reject": "REJECTED",
        "Complaint": "COMPLAINT",
        "Bounce": "SOFT_BOUNCE" if detail.get("bounceType") == "Transient" else "BOUNCED",
    }
    rank = {
        "PENDING": 0,
        "SENDING": 0,
        "UNCERTAIN": 0,
        "RETRY": 0,
        "ACCEPTED": 1,
        "DELAYED": 2,
        "SOFT_BOUNCE": 2,
        "DELIVERED": 3,
        "FAILED": 4,
        "REJECTED": 4,
        "BOUNCED": 5,
        "COMPLAINT": 6,
        "SUPPRESSED": 6,
    }
    state = states.get(kind)
    if state and row.status != "CONFIRMED" and rank.get(state, 0) > rank.get(row.status, 0):
        row.status = state
        row.error_code = None if state in ("ACCEPTED", "DELIVERED") else "SES_" + state
    if not row.last_event_at or utc(row.last_event_at) <= stamp:
        row.last_event = kind
        row.last_event_at = stamp


@router.post("/ipo-alerts/ses-events", status_code=204)
async def ses_events(request: Request, db=Depends(get_session)):
    try:
        body = json.loads(await request.body())
        if not isinstance(body, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid notification") from None
    if request.headers.get("x-amz-sns-message-type") != body.get("Type"):
        raise HTTPException(400, "SNS message type mismatch")
    event = await verify_sns(body)
    if event is not None:
        await ingest_event(db, body["MessageId"], event)
        await db.commit()
    return Response(status_code=204)

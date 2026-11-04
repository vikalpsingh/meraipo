"""Separate email outbox and pre-listing scheduler; never joins the market writer queue."""

import asyncio
import base64
import html
import random
import re
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import case, delete, func, select, update

from apps.api.feedback_routes import insert_for
from apps.worker.tasks import celery
from packages.database import models as m
from packages.database.session import Session, engine
from packages.providers.ses_readiness import sender
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_alerts import (
    CAMPAIGN,
    active,
    control,
    delivery,
    feature_enabled,
    token,
    token_expired,
    within_window,
)
from packages.shared.email_digest import UNSUBSCRIBE, digest_is_current, prepare_digests
from packages.shared.email_policy import production_checks
from packages.shared.email_preferences import current_band, matching_preferences
from packages.shared.email_template import content, eligible_listing, eligible_opening
from packages.shared.market_config import decrypt_secret


async def prepare(db):
    if not await feature_enabled(db):
        return
    config = settings()
    today = m.now().astimezone(ZoneInfo("Asia/Kolkata"))
    if today.hour < config.email_send_hour_ist:
        return
    listings = (
        await db.execute(
            select(m.IPO, m.IPODate, m.ApplicantGuide)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .join(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
            .where(
                (m.IPODate.listing_date == today.date() + timedelta(days=1))
                | (m.IPODate.open_date == today.date()),
                m.Company.is_demo.is_(False),
            )
        )
    ).all()
    await prepare_digests(db, listings, today)
    for ipo, dates, guide in listings:
        if eligible_opening(ipo, dates, guide, today.date()):
            continue
        opening = False
        if not opening and not (
            within_window() and eligible_listing(ipo, dates, guide, today.date())
        ):
            continue
        kind = "ipo_opening" if opening else CAMPAIGN
        band = await current_band(db, ipo) if opening else None
        ipo_id = ipo.id
        await db.execute(
            insert_for(db, m.EmailCampaign)
            .values(
                ipo_id=ipo_id,
                kind=kind,
                scheduled_date=today.date(),
                scheduled_at=datetime.combine(
                    today.date(), time(hour=config.email_send_hour_ist), ZoneInfo("Asia/Kolkata")
                ),
            )
            .on_conflict_do_nothing(index_elements=["ipo_id", "kind", "scheduled_date"])
        )
        campaign = await db.scalar(
            select(m.EmailCampaign).where(
                m.EmailCampaign.ipo_id == ipo_id,
                m.EmailCampaign.kind == kind,
                m.EmailCampaign.scheduled_date == today.date(),
            )
        )
        # An indexed NOT EXISTS allows bounded scheduling across repeated worker ticks.
        exists = (
            select(m.EmailDelivery.id)
            .join(m.EmailCampaign, m.EmailCampaign.id == m.EmailDelivery.campaign_id)
            .where(
                m.EmailDelivery.subscriber_id == m.EmailSubscriber.id,
                m.EmailCampaign.ipo_id == ipo_id,
                m.EmailCampaign.kind == kind,
                m.EmailDelivery.kind == "ALERT",
            )
            .exists()
        )
        subscribers = (
            await db.scalars(
                select(m.EmailSubscriber.id)
                .where(
                    m.EmailSubscriber.verified_at.is_not(None),
                    m.EmailSubscriber.unsubscribed_at.is_(None),
                    m.EmailSubscriber.suppressed_at.is_(None),
                    (
                        m.EmailSubscriber.gmp_band.in_(matching_preferences(band))
                        if opening
                        else m.EmailSubscriber.gmp_band.is_(None)
                    ),
                    ~exists,
                )
                .limit(200)
            )
        ).all()
        for subscriber_id in subscribers:
            reserved = await db.execute(
                insert_for(db, m.EmailReservation)
                .values(subscriber_id=subscriber_id, ipo_id=ipo_id, alert_type=kind)
                .on_conflict_do_nothing(index_elements=["subscriber_id", "ipo_id", "alert_type"])
            )
            if reserved.rowcount != 1:
                continue
            row = delivery(subscriber_id, campaign.id)
            await db.execute(
                insert_for(db, m.EmailDelivery)
                .values(
                    id=row.id,
                    subscriber_id=subscriber_id,
                    campaign_id=campaign.id,
                    kind=row.kind,
                    status=row.status,
                    click_hash=row.click_hash,
                    action_hash=row.action_hash,
                )
                .on_conflict_do_nothing(index_elements=["subscriber_id", "campaign_id"])
            )
    await db.commit()


async def maintain_outbox(db):
    config = settings()
    cutoff = m.now() - timedelta(days=config.email_event_retention_days)
    await db.execute(delete(m.EmailClickEvent).where(m.EmailClickEvent.occurred_at < cutoff))
    await db.execute(delete(m.EmailDeliveryEvent).where(m.EmailDeliveryEvent.occurred_at < cutoff))
    await db.execute(
        update(m.EmailDelivery)
        .execution_options(synchronize_session="fetch")
        .where(
            m.EmailDelivery.status == "SENDING",
            m.EmailDelivery.updated_at < m.now() - timedelta(minutes=15),
        )
        .values(status="UNCERTAIN", error_code="SEND_OUTCOME_UNKNOWN")
    )
    await db.execute(
        update(m.EmailDispatchRun)
        .execution_options(synchronize_session="fetch")
        .where(
            m.EmailDispatchRun.status == "RUNNING",
            m.EmailDispatchRun.created_at < m.now() - timedelta(minutes=15),
        )
        .values(status="FAILED", error_code="WORKER_INTERRUPTED", finished_at=m.now())
    )
    await db.commit()


def opening_gmp(gmp):
    if gmp is None or gmp.value is None:
        return "GMP: unavailable. Check the IPO guide for updates."
    stamp = utc(gmp.observed_at)
    stale = m.now() - stamp > timedelta(hours=settings().gmp_ttl_hours)
    freshness = "Stale — not a current quote" if stale else "Latest recorded snapshot"
    source = (gmp.source_provider or "Source not identified").replace("\n", " ")
    return f"GMP: ₹{gmp.value:,.2f} per share. {freshness}.\nObserved: {stamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p')} IST. Source: {source}."


def ses_send(
    destination,
    subject,
    text,
    unsubscribe,
    delivery_id,
    markup_override=None,
    chart_png=None,
    digest_attachments=None,
):
    config = settings()
    origin = config.public_origin.rstrip("/")

    def anchor(match):
        value = match[0]
        if value.startswith((origin + "/api/ipo-alerts/", origin + "/email-alerts/")):
            return '<a href="' + value + '">' + value + "</a>"
        return value

    markup = re.sub(r"https://[^\s<]+|http://[^\s<]+", anchor, html.escape(text)).replace(
        "\n", "<br>"
    )
    simple = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {
            "Text": {"Data": text, "Charset": "UTF-8"},
            "Html": {"Data": markup_override or "<p>" + markup + "</p>", "Charset": "UTF-8"},
        },
    }
    if chart_png:
        simple["Attachments"] = [
            {
                "RawContent": chart_png,
                "FileName": "ipo-price-chart.png",
                "ContentType": "image/png",
                "ContentDisposition": "INLINE",
                "ContentId": "ipo-price-chart",
                "ContentTransferEncoding": "BASE64",
            }
        ]
    if digest_attachments:
        simple["Attachments"] = [
            {
                "RawContent": base64.b64decode(item["png"]),
                "FileName": item["id"] + ".png",
                "ContentType": "image/png",
                "ContentDisposition": "INLINE",
                "ContentId": item["id"],
                "ContentTransferEncoding": "BASE64",
            }
            for item in digest_attachments
        ]
    if unsubscribe:
        simple["Headers"] = [
            {"Name": "List-Unsubscribe", "Value": "<" + unsubscribe + ">"},
            {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
        ]
    args = {
        "FromEmailAddress": sender(),
        "Destination": {"ToAddresses": [destination]},
        "Content": {"Simple": simple},
        "EmailTags": [{"Name": "delivery_id", "Value": delivery_id}],
    }
    if config.ses_configuration_set:
        args["ConfigurationSetName"] = config.ses_configuration_set
    # Bounded network time; SDK retries disabled because send-email is not idempotent.
    from botocore.config import Config

    return boto3.client(
        "sesv2",
        region_name=config.ses_region,
        config=Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 1}),
    ).send_email(**args)["MessageId"]


async def send_one(db, key, approved=False):
    initial = await db.get(m.EmailDelivery, key, populate_existing=True)
    if not initial:
        return
    if initial.kind == "ALERT":
        if not approved:
            state, checks = await production_checks(db)
            if not state.sending_enabled or not checks["ready"]:
                return
        state = await control(db)
        if not state.sending_enabled or not await feature_enabled(db):
            return
    elif initial.kind == "VERIFY" and not await feature_enabled(db):
        return
    claimed = await db.execute(
        update(m.EmailDelivery)
        .execution_options(synchronize_session="fetch")
        .where(
            m.EmailDelivery.id == key,
            m.EmailDelivery.status.in_(["PENDING", "RETRY"]),
            (m.EmailDelivery.retry_at.is_(None) | (m.EmailDelivery.retry_at <= m.now())),
        )
        .values(status="SENDING", attempt_count=m.EmailDelivery.attempt_count + 1)
    )
    await db.commit()
    if claimed.rowcount != 1:
        return
    row = await db.get(m.EmailDelivery, key, populate_existing=True)
    subscriber = await db.get(m.EmailSubscriber, row.subscriber_id, populate_existing=True)
    if subscriber.suppressed_at or (row.kind == "ALERT" and not active(subscriber)):
        row.status = "SUPPRESSED"
        await db.commit()
        return
    origin = settings().public_origin.rstrip("/")
    action = token(row.id, "action")
    unsubscribe = None
    markup = None
    chart_png = None
    digest_attachments = None
    if row.kind == "VERIFY":
        if token_expired(row):
            row.status = "EXPIRED"
            await db.commit()
            return
        subject = "Confirm your MeraIPO email alerts"
        text = f"You requested MeraIPO email alerts or a preference update. Confirm within 24 hours:\n{origin}/email-alerts/verify#{action}\nIgnore this email if you did not request it."
    else:
        campaign = await db.get(m.EmailCampaign, row.campaign_id)
        if campaign.digest_key:
            if not await digest_is_current(db, campaign, subscriber):
                row.status = "CANCELLED"
                row.error_code = "DIGEST_NO_LONGER_ELIGIBLE"
                await db.commit()
                return
            payload = campaign.digest_payload
            subject = payload["subject"]
            private_url = origin + "/email-alerts/unsubscribe#" + action
            text = payload["text"].replace(UNSUBSCRIBE, private_url)
            markup = payload["html"].replace(UNSUBSCRIBE, private_url)
            digest_attachments = payload["attachments"]
            unsubscribe = origin + "/api/ipo-alerts/unsubscribe/" + action
        else:
            ipo = await db.get(m.IPO, campaign.ipo_id)
            dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
            guide = await db.scalar(
                select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id)
            )
            today = m.now().astimezone(ZoneInfo("Asia/Kolkata")).date()
            if row.kind == "ALERT" and (
                campaign.scheduled_date != today
                or not (
                    (
                        campaign.kind == CAMPAIGN
                        and subscriber.gmp_band is None
                        and within_window()
                        and eligible_listing(ipo, dates, guide, today)
                    )
                    or (
                        campaign.kind == "ipo_opening"
                        and subscriber.gmp_band is not None
                        and eligible_opening(ipo, dates, guide, today)
                        and m.now().astimezone(ZoneInfo("Asia/Kolkata")).hour
                        >= settings().email_send_hour_ist
                    )
                )
            ):
                row.status = "CANCELLED"
                row.error_code = "SCHEDULE_NO_LONGER_ELIGIBLE"
                await db.commit()
                return
            if (
                row.kind == "ALERT"
                and campaign.kind == "ipo_opening"
                and subscriber.gmp_band not in matching_preferences(await current_band(db, ipo))
            ):
                # Revisit later today without consuming a send attempt or blocking other outbox rows.
                row.status = "PENDING"
                row.attempt_count -= 1
                row.retry_at = m.now() + timedelta(minutes=10)
                row.error_code = "GMP_BAND_CHANGED"
                await db.commit()
                return
            company = await db.get(m.Company, ipo.company_id)
            from packages.shared.email_alerts import tracked_url

            category = (
                campaign.kind.split(":")[1]
                if row.kind == "TEST" and campaign.kind.startswith("category:")
                else None
            )
            opening = campaign.kind == "ipo_opening" or category is not None
            public_url = tracked_url(
                origin + "/ipo/" + company.slug,
                company.slug,
                campaign="ipo_opening" if opening else CAMPAIGN,
            )
            unsubscribe = origin + "/api/ipo-alerts/unsubscribe/" + action
            template = await content(
                db,
                ipo.id,
                public_url,
                origin + "/email-alerts/unsubscribe#" + action,
                test=row.kind == "TEST",
                opening=opening,
                test_category=category,
                inline_attachment=True,
            )
            chart_png = template.get("chart_png")
            subject, text, markup = template["subject"], template["text"], template["html"]
    try:
        message_id = await asyncio.to_thread(
            ses_send,
            decrypt_secret(subscriber.email_encrypted),
            subject,
            text,
            unsubscribe,
            row.id,
            markup,
            chart_png,
            digest_attachments,
        )
        await db.execute(
            update(m.EmailDelivery)
            .where(m.EmailDelivery.id == key)
            .values(
                message_id=message_id,
                accepted_at=func.coalesce(m.EmailDelivery.accepted_at, m.now()),
                status=case(
                    (m.EmailDelivery.status.in_(["SENDING", "UNCERTAIN"]), "ACCEPTED"),
                    else_=m.EmailDelivery.status,
                ),
                error_code=case(
                    (m.EmailDelivery.status.in_(["SENDING", "UNCERTAIN"]), None),
                    else_=m.EmailDelivery.error_code,
                ),
            )
        )
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        # Only explicit throttling responses prove the request was not accepted.
        retry = (
            code
            in (
                "Throttling",
                "ThrottlingException",
                "TooManyRequestsException",
                "LimitExceededException",
            )
            and row.attempt_count < settings().email_max_attempts
        )
        status = "RETRY" if retry else "FAILED"
        safe = (
            "SES_THROTTLED"
            if code
            in (
                "Throttling",
                "ThrottlingException",
                "TooManyRequestsException",
                "LimitExceededException",
            )
            else "SES_PERMANENT_REJECTION"
        )
        safe = {
            "AccessDeniedException": "SES_ACCESS_DENIED",
            "AccessDenied": "SES_ACCESS_DENIED",
            "MessageRejected": "SES_MESSAGE_REJECTED",
            "MailFromDomainNotVerifiedException": "SES_MAIL_FROM_UNVERIFIED",
            "NotFoundException": "SES_RESOURCE_NOT_FOUND",
            "SendingPausedException": "SES_SENDING_PAUSED",
            "AccountSuspendedException": "SES_ACCOUNT_SUSPENDED",
        }.get(code, safe)
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400) >= 500:
            status = "UNCERTAIN"
            safe = "SES_SEND_OUTCOME_UNKNOWN"
        await db.execute(
            update(m.EmailDelivery)
            .where(m.EmailDelivery.id == key, m.EmailDelivery.status == "SENDING")
            .values(
                status=status,
                error_code=safe,
                retry_at=m.now()
                + timedelta(seconds=min(3600, 30 * 2**row.attempt_count) + random.uniform(0, 30))
                if retry
                else None,
            )
        )
    except Exception:
        await db.execute(
            update(m.EmailDelivery)
            .where(m.EmailDelivery.id == key, m.EmailDelivery.status == "SENDING")
            .values(status="UNCERTAIN", error_code="SES_SEND_OUTCOME_UNKNOWN")
        )
    await db.commit()


@celery.task(name="meraipo.email_tick", soft_time_limit=210, time_limit=240)
def email_tick():
    async def run():
        run_id = None
        owner = str(uuid4())
        try:
            async with Session() as db:
                state = await control(db)
                state.scheduler_seen_at = m.now()
                await db.commit()
                locked = await db.execute(
                    update(m.EmailControl)
                    .execution_options(synchronize_session="fetch")
                    .where(
                        m.EmailControl.id == "email",
                        m.EmailControl.lease_until.is_(None)
                        | (m.EmailControl.lease_until < m.now()),
                    )
                    .values(lease_until=m.now() + timedelta(minutes=5), lease_owner=owner)
                )
                await db.commit()
                if locked.rowcount != 1:
                    return {"status": "BUSY"}
                await maintain_outbox(db)
                job = m.EmailDispatchRun(status="RUNNING")
                db.add(job)
                await db.commit()
                run_id = job.id
                state, checks = await production_checks(db)
                approved = state.sending_enabled and checks["ready"]
                if approved:
                    await prepare(db)
                allowed = (
                    ["TEST"]
                    + (["VERIFY"] if await feature_enabled(db) else [])
                    + (["ALERT"] if approved else [])
                )
                aws = checks["aws"]
                rate = min(settings().email_max_per_second, aws.get("max_rate") or 1)
                capacity = min(
                    settings().email_batch_size,
                    int(aws.get("remaining_quota") or 0),
                    max(1, int(150 * rate)),
                )
                keys = (
                    await db.scalars(
                        select(m.EmailDelivery.id)
                        .where(
                            m.EmailDelivery.kind.in_(allowed),
                            m.EmailDelivery.status.in_(["PENDING", "RETRY"]),
                            m.EmailDelivery.retry_at.is_(None)
                            | (m.EmailDelivery.retry_at <= m.now()),
                        )
                        .order_by(m.EmailDelivery.created_at)
                        .limit(capacity)
                    )
                ).all()
                for key in keys:
                    await send_one(db, key, approved=approved)
                    job.processed += 1
                    current = await db.get(m.EmailDelivery, key, populate_existing=True)
                    if current.status == "RETRY":
                        break
                    await asyncio.sleep(1 / rate)
                job.status = "COMPLETE" if approved else "TEST_ONLY"
                job.finished_at = m.now()
                await db.commit()
                return {"status": job.status, "processed": job.processed}
        except Exception:
            if run_id:
                async with Session() as db:
                    await db.execute(
                        update(m.EmailDispatchRun)
                        .where(m.EmailDispatchRun.id == run_id)
                        .values(status="FAILED", error_code="DISPATCH_FAILED", finished_at=m.now())
                    )
                    await db.commit()
            return {"status": "FAILED"}
        finally:
            if run_id:
                async with Session() as db:
                    await db.execute(
                        update(m.EmailControl)
                        .where(m.EmailControl.id == "email", m.EmailControl.lease_owner == owner)
                        .values(lease_until=None, lease_owner=None)
                    )
                    await db.commit()
            await engine.dispose()
            from apps.api.cache import client

            await client.aclose()

    return asyncio.run(run())

"""Immutable morning snapshots, shared rendering, individually addressed delivery."""

import base64
import re
from datetime import datetime, time
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from apps.api.feedback_routes import insert_for
from packages.database import models as m
from packages.shared.config import settings
from packages.shared.email_alerts import delivery, tracked_url
from packages.shared.email_preferences import (
    BANDS,
    CATEGORY_LABELS,
    current_band,
    matching_preferences,
)
from packages.shared.email_template import content, eligible_opening

UNSUBSCRIBE = "__MERAIPO_DIGEST_UNSUBSCRIBE__"
IST = ZoneInfo("Asia/Kolkata")


async def prepare_digests(db, listings, today):
    # Retire pending per-IPO opening alerts when upgrading to daily digests.
    await db.execute(
        update(m.EmailDelivery)
        .where(
            m.EmailDelivery.kind == "ALERT",
            m.EmailDelivery.status != "CANCELLED",
            m.EmailDelivery.status.in_(["PENDING", "RETRY"]),
            m.EmailDelivery.campaign_id.in_(
                select(m.EmailCampaign.id).where(m.EmailCampaign.kind == "ipo_opening")
            ),
        )
        .values(status="CANCELLED", error_code="REPLACED_BY_DAILY_DIGEST")
    )
    key_prefix = today.date().isoformat() + ":"
    campaigns = list(
        (
            await db.scalars(
                select(m.EmailCampaign).where(m.EmailCampaign.digest_key.startswith(key_prefix))
            )
        ).all()
    )
    if not campaigns:
        opening = [
            (ipo, dates, guide)
            for ipo, dates, guide in listings
            if eligible_opening(ipo, dates, guide, today.date())
        ]
        if not opening:
            return
        rendered = []
        origin = settings().public_origin.rstrip("/")
        for ipo, _dates, _guide in opening:
            company = await db.get(m.Company, ipo.company_id)
            band = await current_band(db, ipo)
            item = await content(
                db,
                ipo.id,
                tracked_url(origin + "/ipo/" + company.slug, company.slug, campaign="ipo_opening"),
                UNSUBSCRIBE,
                opening=True,
                inline_attachment=True,
            )
            # Each card keeps its image CID distinct inside the combined message.
            image_id = "ipo-" + ipo.id
            item["html"] = item["html"].replace("cid:ipo-price-chart", "cid:" + image_id)
            attachment = None
            if item.get("chart_png"):
                attachment = {
                    "id": image_id,
                    "png": base64.b64encode(item["chart_png"]).decode("ascii"),
                }
            body = re.search(r"<body[^>]*>(.*)</body>", item["html"], flags=re.S).group(1)
            # A single unsubscribe footer belongs to the digest, not each card.
            body = re.sub(r'<tr><td bgcolor="#f2f6f4".*?</td></tr>', "", body, flags=re.S)
            text = item["text"].split("\nUnsubscribe: ")[0]
            rendered.append((ipo.id, band, body, text, attachment))
        # Write all categories in one transaction, including empty categories.
        # Subsequent ticks reuse this first snapshot, even when prices change.
        for category in BANDS:
            matches = [item for item in rendered if category in matching_preferences(item[1])]
            label = CATEGORY_LABELS[category]
            title = f"MeraIPO | {len(matches)} IPOs opening today | {label}"
            stamp = today.strftime("%d %b %Y, %I:%M %p IST")
            payload = {
                "category": category,
                "ipo_ids": [item[0] for item in matches],
                "subject": title,
                "text": title
                + "\nSnapshot: "
                + stamp
                + "\n\n"
                + "\n\n".join(item[3] for item in matches)
                + "\nUnsubscribe: "
                + UNSUBSCRIBE,
                "html": '<html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#edf3f1;font-family:Arial,sans-serif">'
                + f'<h1 style="font-size:22px;text-align:center">{escape(title)}</h1><p style="text-align:center">Snapshot: {stamp}</p>'
                + "".join(item[2] for item in matches)
                + f'<p style="text-align:center"><a href="{UNSUBSCRIBE}">Unsubscribe from IPO alerts</a></p></body></html>',
                "attachments": [item[4] for item in matches if item[4]],
            }
            await db.execute(
                insert_for(db, m.EmailCampaign)
                .values(
                    ipo_id=opening[0][0].id,
                    kind="digest_" + category,
                    digest_key=key_prefix + category,
                    digest_payload=payload,
                    scheduled_date=today.date(),
                    scheduled_at=datetime.combine(
                        today.date(), time(hour=settings().email_send_hour_ist), IST
                    ),
                )
                .on_conflict_do_nothing(index_elements=["digest_key"])
            )
        await db.commit()
        campaigns = list(
            (
                await db.scalars(
                    select(m.EmailCampaign).where(m.EmailCampaign.digest_key.startswith(key_prefix))
                )
            ).all()
        )
    for campaign in campaigns:
        payload = campaign.digest_payload
        for ipo_id in payload["ipo_ids"]:
            await db.execute(
                insert_for(db, m.EmailDigestMember)
                .values(campaign_id=campaign.id, ipo_id=ipo_id)
                .on_conflict_do_nothing()
            )

        if not payload["ipo_ids"]:
            continue
        # Includes earlier per-IPO alerts on deployment day, preventing duplicate contact.
        contacted = (
            select(m.EmailDelivery.id)
            .join(m.EmailCampaign, m.EmailDelivery.campaign_id == m.EmailCampaign.id)
            .where(
                m.EmailDelivery.subscriber_id == m.EmailSubscriber.id,
                m.EmailDelivery.kind == "ALERT",
                m.EmailDelivery.status != "CANCELLED",
                m.EmailCampaign.scheduled_date == today.date(),
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
                    m.EmailSubscriber.gmp_band == payload["category"],
                    ~contacted,
                )
                .order_by(m.EmailSubscriber.id)
                .limit(200)
            )
        ).all()
        for subscriber_id in subscribers:
            row = delivery(subscriber_id, campaign.id)
            await db.execute(
                insert_for(db, m.EmailDelivery)
                .values(
                    id=row.id,
                    subscriber_id=subscriber_id,
                    campaign_id=campaign.id,
                    kind="ALERT",
                    status="PENDING",
                    click_hash=row.click_hash,
                    action_hash=row.action_hash,
                    digest_date=today.date(),
                )
                .on_conflict_do_nothing(index_elements=["subscriber_id", "digest_date"])
            )
    await db.commit()


async def digest_is_current(db, campaign, subscriber):
    now = m.now().astimezone(IST)
    if campaign.scheduled_date != now.date() or now.hour < settings().email_send_hour_ist:
        return False
    if subscriber.gmp_band != campaign.digest_payload["category"]:
        return False
    for ipo_id in campaign.digest_payload["ipo_ids"]:
        ipo = await db.get(m.IPO, ipo_id)
        company = await db.get(m.Company, ipo.company_id) if ipo else None
        dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo_id))
        guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo_id))
        if not company or company.is_demo or not eligible_opening(ipo, dates, guide, now.date()):
            return False
    return True

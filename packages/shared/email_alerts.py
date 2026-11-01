"""Private subscription identities and canonical tracked links."""

import hashlib
import hmac
import re
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from packages.database import models as m
from packages.shared.config import settings

CAMPAIGN = "ipo_prelisting"


async def feature_enabled(db):
    flag = await db.get(m.FeatureFlag, "email_alerts", populate_existing=True)
    return bool(flag and flag.enabled)


def token(subject, purpose):
    secret = settings().email_token_secret.get_secret_value()
    if len(secret) < 32:
        raise ValueError("EMAIL_TOKEN_SECRET_REQUIRED")
    return hmac.new(secret.encode(), f"{purpose}:{subject}".encode(), hashlib.sha256).hexdigest()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def normalized_email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value
    ):
        raise ValueError("Enter a valid email address")
    return value


def active(subscriber):
    return bool(
        subscriber.verified_at and not subscriber.unsubscribed_at and not subscriber.suppressed_at
    )


def delivery(subscriber_id, campaign_id=None):
    key = str(uuid4())
    return m.EmailDelivery(
        id=key,
        subscriber_id=subscriber_id,
        campaign_id=campaign_id,
        kind="ALERT" if campaign_id else "VERIFY",
        status="PENDING",
        click_hash=digest(token(key, "click")),
        action_hash=digest(token(key, "action")),
    )


def tracked_url(url, identifier, campaign=CAMPAIGN):
    if campaign not in ("ipo_opening", "ipo_prelisting"):
        raise ValueError("UNSUPPORTED_EMAIL_CAMPAIGN")
    origin = urlsplit(settings().public_origin)
    parts = urlsplit(url)
    if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc) or not re.fullmatch(
        r"/ipo/[a-z0-9]+(?:-[a-z0-9]+)*", parts.path
    ):
        raise ValueError("CANONICAL_IPO_URL_REQUIRED")
    params = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    params.extend(
        dict(
            utm_source="meraipo_email",
            utm_medium="email",
            utm_campaign=campaign,
            utm_content=identifier,
        ).items()
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def classify_click(user_agent, purpose=""):
    if (
        re.search(
            r"bot|crawl|spider|scanner|preview|proofpoint|mimecast|barracuda|safelinks",
            user_agent,
            re.I,
        )
        or "prefetch" in purpose.lower()
    ):
        return "SUSPECTED_BOT"
    return "UNCLASSIFIED"  # An HTTP GET alone cannot prove a human visit.


def token_expired(row):
    from packages.shared.calculations import utc

    return utc(row.created_at) < m.now() - timedelta(hours=24)


async def control(db, lock=False):
    from apps.api.feedback_routes import insert_for

    await db.execute(
        insert_for(db, m.EmailControl)
        .values(id="email", sending_enabled=False)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return await db.get(m.EmailControl, "email", populate_existing=True, with_for_update=lock)


def within_window():
    from zoneinfo import ZoneInfo

    c = settings()
    stamp = m.now().astimezone(ZoneInfo("Asia/Kolkata"))
    return (
        c.email_send_hour_ist <= stamp.hour < min(24, c.email_send_hour_ist + c.email_catchup_hours)
    )

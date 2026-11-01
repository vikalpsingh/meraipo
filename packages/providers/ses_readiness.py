"""Read-only AWS readiness. No credentials, subscriber data or raw AWS responses leave this module."""

import asyncio
import hashlib
import json
from email.utils import parseaddr

import boto3
import httpx
from botocore.config import Config

from apps.api.cache import client as cache
from packages.shared.config import settings


def config_hash():
    c = settings()
    return hashlib.sha256(
        "|".join(
            [
                c.email_from,
                c.email_from_name,
                c.ses_region,
                c.ses_configuration_set,
                c.ses_sns_topic_arn,
                c.public_origin,
            ]
        ).encode()
    ).hexdigest()


def aws_client(service):
    return boto3.client(
        service,
        region_name=settings().ses_region,
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}),
    )


def sender():
    c = settings()
    from email.utils import formataddr

    return formataddr((c.email_from_name, c.email_from))


async def readiness(refresh=False):
    c = settings()
    key = "ses-readiness:" + config_hash()
    data = {
        "status": "NOT_CONFIGURED",
        "ready": False,
        "checks": {},
        "max_rate": None,
        "remaining_quota": None,
        "sender": sender(),
    }
    if (
        not c.email_alerts_enabled
        or not c.ses_configuration_set
        or not c.ses_sns_topic_arn
        or "<" in c.ses_sns_topic_arn
    ):
        return data
    address = parseaddr(c.email_from)[1]
    if address != "alerts@meraipo.com" or not c.public_origin.startswith("https://"):
        data["status"] = "INVALID_CONFIGURATION"
        return data

    if not refresh:
        try:
            value = await cache.get(key)
            if value:
                return json.loads(value)
        except Exception:
            pass

    def query():
        ses = aws_client("sesv2")
        sns = aws_client("sns")
        identity = ses.get_email_identity(EmailIdentity="meraipo.com")
        account = ses.get_account()
        destinations = ses.get_configuration_set_event_destinations(
            ConfigurationSetName=c.ses_configuration_set
        )
        subscriptions = []
        next_token = None
        for _ in range(20):
            args = {"TopicArn": c.ses_sns_topic_arn}
            if next_token:
                args["NextToken"] = next_token
            page = sns.list_subscriptions_by_topic(**args)
            subscriptions.extend(page.get("Subscriptions", []))
            next_token = page.get("NextToken")
            if not next_token:
                break
        return identity, account, destinations, subscriptions

    try:
        identity, account, destinations, subscriptions = await asyncio.to_thread(query)
        quota = account.get("SendQuota", {})
        checks = data["checks"]
        checks["identity_verified"] = identity.get("VerifiedForSendingStatus") is True
        checks["dkim"] = identity.get("DkimAttributes", {}).get("Status") == "SUCCESS"
        mailfrom = identity.get("MailFromAttributes", {})
        checks["custom_mail_from"] = (
            mailfrom.get("MailFromDomain") == "alerts.meraipo.com"
            and mailfrom.get("MailFromDomainStatus") == "SUCCESS"
        )
        checks["production_access"] = account.get("ProductionAccessEnabled") is True
        checks["sending_allowed"] = account.get("SendingEnabled") is True
        data["max_rate"] = quota.get("MaxSendRate")
        data["remaining_quota"] = max(
            0, quota.get("Max24HourSend", 0) - quota.get("SentLast24Hours", 0)
        )
        checks["quota"] = bool(data["max_rate"] and data["remaining_quota"])
        required = {"SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"}
        events = set()
        for destination in destinations.get("EventDestinations", []):
            if (
                destination.get("Enabled")
                and destination.get("SnsDestination", {}).get("TopicArn") == c.ses_sns_topic_arn
            ):
                events.update(destination.get("MatchingEventTypes", []))
        checks["ses_events"] = required.issubset(events)
        checks["sns_subscription"] = any(
            row.get("Protocol") == "https"
            and row.get("Endpoint") == c.public_origin.rstrip("/") + "/api/v1/ipo-alerts/ses-events"
            and row.get("SubscriptionArn", "").startswith("arn:")
            for row in subscriptions
        )
        async with httpx.AsyncClient(timeout=5) as http:

            async def txt(name):
                response = await http.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": name, "type": "TXT"},
                    headers={"accept": "application/dns-json"},
                )
                response.raise_for_status()
                result = response.json()
                if result.get("Status") != 0:
                    return ""
                return " ".join(
                    a.get("data", "").replace('"', "")
                    for a in result.get("Answer", [])
                    if a.get("type") == 16
                )

            spf, dmarc = await asyncio.gather(txt("alerts.meraipo.com"), txt("_dmarc.meraipo.com"))
        checks["spf"] = "v=spf1" in spf and "include:amazonses.com" in spf
        checks["dmarc"] = "v=DMARC1" in dmarc and "p=" in dmarc
        data["ready"] = all(checks.values())
        data["status"] = "READY" if data["ready"] else "ACTION_REQUIRED"
    except Exception:
        data["status"] = "UNAVAILABLE"
        data["ready"] = False
        data["message"] = (
            "AWS or DNS checks unavailable. Check scoped IAM access, credentials, network and SES region."
        )
    try:
        await cache.setex(key, 60, json.dumps(data))
    except Exception:
        pass
    return data

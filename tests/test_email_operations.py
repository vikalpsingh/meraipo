"""SES operational safety checks with mocked AWS only."""

from datetime import timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr
from sqlalchemy import delete, select

from apps.api.email_routes import ingest_event
from apps.worker.email_alerts import prepare, send_one
from packages.database import models as m
from packages.providers.ses_readiness import config_hash
from packages.shared.config import settings
from packages.shared.email_alerts import control, delivery
from packages.shared.email_template import content, eligible_listing
from packages.shared.market_config import encrypt_secret


@pytest.fixture
async def setup_email(db, monkeypatch):
    for key, value in {
        "ipo_email_sending_enabled": True,
        "email_token_secret": SecretStr("test-email-operations-secret-more-than-32"),
        "email_from": "alerts@meraipo.com",
        "email_from_name": "MeraIPO Alerts",
        "ses_configuration_set": "meraipo-ipo-alerts",
    }.items():
        monkeypatch.setattr(settings(), key, value)
    monkeypatch.setattr("apps.worker.email_alerts.within_window", lambda: True)
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    state = await control(db)
    state.sending_enabled = True
    state.scheduler_seen_at = m.now()
    ipo = await db.scalar(select(m.IPO))
    ipo.status = "CLOSED"
    ipo.raw_status = None
    company = await db.get(m.Company, ipo.company_id)
    company.is_demo = False
    today = m.now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    dates.listing_date = today + timedelta(days=1)
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    guide.schedule_status = "CONFIRMED"
    guide.verification_status = "VERIFIED"
    sub = m.EmailSubscriber(
        email_hash="operations-fixture",
        email_encrypted=encrypt_secret("person@example.com"),
        consent_at=m.now(),
        verified_at=m.now(),
    )
    campaign = m.EmailCampaign(ipo_id=ipo.id, kind="ipo_prelisting", scheduled_date=today)
    db.add_all([sub, campaign])
    await db.flush()
    row = delivery(sub.id, campaign.id)
    db.add(row)
    await db.commit()
    return ipo, dates, guide, sub, campaign, row, state


async def test_throttle_retries_but_ambiguous_error_does_not(db, setup_email, monkeypatch):
    *_, row, state = setup_email

    def throttled(*args):
        raise ClientError(
            {
                "Error": {"Code": "TooManyRequestsException"},
                "ResponseMetadata": {"HTTPStatusCode": 429},
            },
            "SendEmail",
        )

    monkeypatch.setattr("apps.worker.email_alerts.ses_send", throttled)
    await send_one(db, row.id, approved=True)
    assert row.status == "RETRY" and row.attempt_count == 1 and row.retry_at is not None
    await send_one(db, row.id, approved=True)
    assert row.attempt_count == 1
    row.retry_at = m.now() - timedelta(seconds=1)
    await db.commit()

    def timeout(*args):
        raise TimeoutError()

    monkeypatch.setattr("apps.worker.email_alerts.ses_send", timeout)
    await send_one(db, row.id, approved=True)
    assert row.status == "UNCERTAIN"
    await send_one(db, row.id, approved=True)
    assert row.attempt_count == 2


async def test_unconfirmed_or_unsubscribed_never_sent(db, setup_email, monkeypatch):
    ipo, dates, guide, sub, campaign, row, state = setup_email
    mock = AsyncMock()
    monkeypatch.setattr("apps.worker.email_alerts.ses_send", mock)
    guide.schedule_status = "TENTATIVE"
    await db.commit()
    await send_one(db, row.id, approved=True)
    assert row.status == "CANCELLED"
    mock.assert_not_called()
    row.status = "PENDING"
    guide.schedule_status = "CONFIRMED"
    sub.unsubscribed_at = m.now()
    await db.commit()
    await send_one(db, row.id, approved=True)
    assert row.status == "SUPPRESSED"
    mock.assert_not_called()


async def test_date_revision_does_not_duplicate(db, setup_email):
    ipo, dates, guide, sub, campaign, row, state = setup_email
    row.accepted_at = m.now()
    row.status = "ACCEPTED"
    campaign.scheduled_date -= timedelta(days=3)
    await db.commit()
    await prepare(db)
    await prepare(db)
    rows = (
        await db.scalars(select(m.EmailDelivery).where(m.EmailDelivery.subscriber_id == sub.id))
    ).all()
    assert len(rows) == 1


async def test_template_escapes_and_reports_missing_values(db, setup_email):
    ipo, dates, guide, *_ = setup_email
    company = await db.get(m.Company, ipo.company_id)
    company.name = "<img src=x onerror=alert(1)>"
    ipo.issue_price = None
    ipo.price_high = None
    await db.execute(delete(m.GMP).where(m.GMP.ipo_id == ipo.id))
    await db.commit()
    rendered = await content(
        db,
        ipo.id,
        "https://meraipo.com/ipo/example?utm_campaign=ipo_prelisting",
        "https://meraipo.com/email-alerts",
        test=True,
    )
    assert "&lt;img" in rendered["html"] and "<img src=x" not in rendered["html"]
    assert "N/A" in rendered["text"] and rendered["subject"].startswith("TEST")
    assert "not a guaranteed" in rendered["text"]
    assert not eligible_listing(ipo, dates, None, m.now().date())


async def test_feedback_terminal_status_and_soft_bounce(db, setup_email):
    *_, row, state = setup_email
    stamp = m.now().isoformat()
    event = {
        "eventType": "DeliveryDelay",
        "mail": {"messageId": "ops-message", "timestamp": stamp, "tags": {"delivery_id": [row.id]}},
        "deliveryDelay": {"timestamp": stamp},
    }
    await ingest_event(db, "delay", event)
    await db.commit()
    assert row.status == "DELAYED"
    event["eventType"] = "Bounce"
    event["bounce"] = {"timestamp": stamp, "bounceType": "Transient"}
    await ingest_event(db, "soft", event)
    await db.commit()
    subscriber = await db.get(m.EmailSubscriber, row.subscriber_id)
    assert subscriber.suppressed_at is None
    event["eventType"] = "Complaint"
    event["complaint"] = {"timestamp": stamp}
    await ingest_event(db, "complaint", event)
    await db.commit()
    assert row.status == "COMPLAINT"
    for kind in ["Send", "Delivery"]:
        event["eventType"] = kind
        event[kind.lower()] = {"timestamp": stamp}
        await ingest_event(db, kind, event)
        await db.commit()
        assert row.status == "COMPLAINT"
    assert subscriber.suppressed_at is not None


async def test_admin_enable_requires_test_and_health(admin_client, db, setup_email, monkeypatch):
    *_, row, state = setup_email
    fake = AsyncMock(
        return_value={
            "ready": True,
            "status": "READY",
            "checks": {},
            "max_rate": 1,
            "remaining_quota": 100,
        }
    )
    monkeypatch.setattr("packages.shared.email_policy.readiness", fake)
    response = await admin_client.put("/api/v1/admin/email/sending", json={"enabled": True})
    assert response.status_code == 409
    row.kind = "TEST"
    row.unsubscribed_at = m.now()
    row.delivered_at = m.now()
    state.test_delivery_id = row.id
    state.test_received_at = m.now()
    state.test_config_hash = config_hash()
    await db.commit()
    assert (
        await admin_client.put("/api/v1/admin/email/sending", json={"enabled": True})
    ).status_code == 200
    fake.side_effect = AssertionError("Disable must not call AWS")
    assert (
        await admin_client.put("/api/v1/admin/email/sending", json={"enabled": False})
    ).status_code == 200
    assert not state.sending_enabled


async def test_admin_auth_and_sns_header_mismatch(client):
    assert (await client.get("/api/v1/admin/email/status")).status_code == 401
    assert (
        await client.post(
            "/api/v1/ipo-alerts/ses-events",
            json={"Type": "Notification"},
            headers={"x-amz-sns-message-type": "SubscriptionConfirmation"},
        )
    ).status_code == 400


async def test_readiness_missing_config_does_not_call_aws(monkeypatch):
    from packages.providers.ses_readiness import readiness

    monkeypatch.setattr(settings(), "ses_sns_topic_arn", "")

    class Cache:
        async def get(self, key):
            return None

    monkeypatch.setattr("packages.providers.ses_readiness.cache", Cache())

    def forbidden(*args):
        raise AssertionError("AWS must not be called")

    monkeypatch.setattr("packages.providers.ses_readiness.aws_client", forbidden)
    result = await readiness(True)
    assert result["status"] == "NOT_CONFIGURED" and not result["ready"]


def test_operations_migration_roundtrip():
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    first = importlib.import_module("packages.database.migrations.versions.20261031_email_alerts")
    second = importlib.import_module(
        "packages.database.migrations.versions.20261101_email_operations"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            first.upgrade()
            second.upgrade()
            assert "email_control" in inspect(connection).get_table_names()
            assert (
                connection.exec_driver_sql("SELECT sending_enabled FROM email_control").scalar()
                == 0
            )
            second.downgrade()
            first.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()


async def test_readiness_checks_aws_and_dns(monkeypatch):
    import httpx

    from packages.providers.ses_readiness import readiness

    for key, value in {
        "email_from": "alerts@meraipo.com",
        "public_origin": "https://meraipo.com",
        "ses_configuration_set": "meraipo-ipo-alerts",
        "ses_sns_topic_arn": "arn:aws:sns:ap-south-1:123456789012:meraipo-ses-events",
    }.items():
        monkeypatch.setattr(settings(), key, value)

    class AWS:
        def get_email_identity(self, **kwargs):
            return {
                "VerifiedForSendingStatus": True,
                "DkimAttributes": {"Status": "SUCCESS"},
                "MailFromAttributes": {
                    "MailFromDomain": "alerts.meraipo.com",
                    "MailFromDomainStatus": "SUCCESS",
                },
            }

        def get_account(self):
            return {
                "ProductionAccessEnabled": True,
                "SendingEnabled": True,
                "SendQuota": {"MaxSendRate": 2, "Max24HourSend": 100, "SentLast24Hours": 5},
            }

        def get_configuration_set_event_destinations(self, **kwargs):
            return {
                "EventDestinations": [
                    {
                        "Enabled": True,
                        "SnsDestination": {"TopicArn": settings().ses_sns_topic_arn},
                        "MatchingEventTypes": [
                            "SEND",
                            "DELIVERY",
                            "BOUNCE",
                            "COMPLAINT",
                            "REJECT",
                            "DELIVERY_DELAY",
                        ],
                    }
                ]
            }

        def list_subscriptions_by_topic(self, **kwargs):
            return {
                "Subscriptions": [
                    {
                        "Protocol": "https",
                        "Endpoint": "https://meraipo.com/api/v1/ipo-alerts/ses-events",
                        "SubscriptionArn": "arn:aws:sns:fixture",
                    }
                ]
            }

    class Cache:
        async def setex(self, *args):
            pass

    monkeypatch.setattr("packages.providers.ses_readiness.aws_client", lambda service: AWS())
    monkeypatch.setattr("packages.providers.ses_readiness.cache", Cache())
    original = httpx.AsyncClient

    def dns(request):
        value = (
            "v=spf1 include:amazonses.com -all"
            if request.url.params["name"] == "alerts.meraipo.com"
            else "v=DMARC1; p=none"
        )
        return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 16, "data": value}]})

    monkeypatch.setattr(
        "packages.providers.ses_readiness.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(dns), **kwargs),
    )
    result = await readiness(True)
    assert result["ready"] and result["max_rate"] == 2 and result["remaining_quota"] == 95

    def inaccessible(service):
        raise RuntimeError("no credentials")

    monkeypatch.setattr("packages.providers.ses_readiness.aws_client", inaccessible)
    result = await readiness(True)
    assert result["status"] == "UNAVAILABLE" and not result["ready"]


async def test_dispatch_window_is_ist_and_bounded(monkeypatch):
    from datetime import datetime, timezone

    from packages.shared.email_alerts import within_window

    monkeypatch.setattr(settings(), "email_send_hour_ist", 8)
    monkeypatch.setattr(settings(), "email_catchup_hours", 4)
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 11, 1, 2, 29, tzinfo=timezone.utc))
    assert not within_window()
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 11, 1, 2, 30, tzinfo=timezone.utc))
    assert within_window()
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc))
    assert not within_window()


async def test_crashed_sends_are_reconciled_even_with_bulk_off(db, setup_email):
    from apps.worker.email_alerts import maintain_outbox

    *_, row, state = setup_email
    state.sending_enabled = False
    row.status = "SENDING"
    row.updated_at = m.now() - timedelta(minutes=20)
    job = m.EmailDispatchRun(status="RUNNING", created_at=m.now() - timedelta(minutes=20))
    db.add(job)
    await db.commit()
    await maintain_outbox(db)
    await db.refresh(row)
    await db.refresh(job)
    assert row.status == "UNCERTAIN" and row.error_code == "SEND_OUTCOME_UNKNOWN"
    assert job.status == "FAILED" and job.error_code == "WORKER_INTERRUPTED"


async def test_control_center_status_unconfigured(admin_client, monkeypatch):
    monkeypatch.setattr(settings(), "ses_sns_topic_arn", "")
    response = await admin_client.get("/api/v1/admin/email/status")
    assert response.status_code == 200, response.text
    value = response.json()
    assert not value["sending_enabled"]
    assert value["readiness"]["aws"]["status"] == "NOT_CONFIGURED"
    assert value["counts"]["SCHEDULED"] == 0
    assert "email_encrypted" not in response.text


async def test_admin_category_batch_sends_four_distinct_tests(
    admin_client, db, setup_email, monkeypatch
):
    from packages.shared.email_preferences import BANDS, CATEGORY_LABELS

    ipo, *_, state = setup_email
    monkeypatch.setattr(settings(), "public_origin", "https://meraipo.com")
    monkeypatch.setattr(
        "apps.api.email_admin.readiness",
        AsyncMock(return_value={"checks": {"identity_verified": True, "sending_allowed": True}}),
    )
    admin_client.headers["origin"] = settings().public_origin
    payload = {"ipo_id": ipo.id, "email": "tester@example.com", "categories": list(BANDS)}
    response = await admin_client.post("/api/v1/admin/email/category-tests", json=payload)
    assert response.status_code == 202, response.text
    ids = response.json()["ids"]
    assert len(set(ids)) == 4
    sent = []
    monkeypatch.setattr(
        "apps.worker.email_alerts.ses_send", lambda *args: sent.append(args) or f"test-{len(sent)}"
    )
    for key in ids:
        await send_one(db, key)
    assert len(sent) == 4
    for args, band in zip(sent, BANDS, strict=True):
        assert args[0] == "tester@example.com"
        assert args[1].startswith(f"TEST — {CATEGORY_LABELS[band]} |")
        assert "Latest GMP matches this preference" in args[2]
    assert (
        await admin_client.post("/api/v1/admin/email/category-tests", json=payload)
    ).status_code == 429
    await db.refresh(state)
    assert state.test_delivery_id is None

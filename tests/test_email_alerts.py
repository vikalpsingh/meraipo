"""Focused regression coverage; no live SES/GA4 calls."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, select

from apps.api.email_analytics import bounds, rate
from apps.api.email_routes import ingest_event
from apps.worker.email_alerts import prepare, send_one
from packages.database import models as m
from packages.providers.ga4 import reports
from packages.providers.ses_events import verify_sns
from packages.shared.config import settings
from packages.shared.email_alerts import classify_click, delivery, token, tracked_url
from packages.shared.market_config import encrypt_secret


@pytest.fixture(autouse=True)
def email_config(monkeypatch):
    monkeypatch.setattr("apps.worker.email_alerts.within_window", lambda: True)
    config = settings()
    for key, value in {
        "email_alerts_enabled": True,
        "email_from": "alerts@example.com",
        "email_token_secret": SecretStr("test-only-email-token-secret-32-characters"),
        "ga4_property_id": "",
        "ga4_service_account_file": "",
        "email_send_hour_ist": 0,
    }.items():
        monkeypatch.setattr(config, key, value)


async def alert(db):
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    ipo = await db.scalar(select(m.IPO))
    sub = m.EmailSubscriber(
        email_hash=token("a@example.com", "email"),
        email_encrypted=encrypt_secret("a@example.com"),
        consent_at=m.now(),
        verified_at=m.now(),
    )
    campaign = m.EmailCampaign(ipo_id=ipo.id, kind="ipo_prelisting", scheduled_date=m.now().date())
    db.add_all([sub, campaign])
    await db.flush()
    row = delivery(sub.id, campaign.id)
    db.add(row)
    await db.commit()
    return sub, campaign, row


def test_tracking_is_canonical_and_preserves_query():
    parsed = urlsplit(
        tracked_url("http://localhost:3000/ipo/example?view=summary&utm_source=old", "example")
    )
    params = parse_qs(parsed.query)
    assert params["view"] == ["summary"]
    assert params["utm_source"] == ["meraipo_email"]
    assert params["utm_content"] == ["example"]
    for target in [
        "https://evil.example/ipo/example",
        "http://localhost:3000/ipo/../admin",
        "//evil.example/ipo/example",
    ]:
        with pytest.raises(ValueError):
            tracked_url(target, "example")


def test_ist_boundaries_and_denominators():
    _, _, lo, hi = bounds(date(2026, 1, 2), date(2026, 1, 2))
    assert lo == datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)
    assert hi - lo == timedelta(days=1)
    assert rate(2, 4) == 50
    assert rate(0, 0) is None
    with pytest.raises(HTTPException):
        bounds(date(2026, 1, 3), date(2026, 1, 2))
    assert classify_click("Proofpoint scanner") == "SUSPECTED_BOT"
    assert classify_click("browser", "prefetch") == "SUSPECTED_BOT"
    assert classify_click("browser") == "UNCLASSIFIED"


async def test_subscription_dedup_confirm_unsubscribe(client, db):
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    await db.commit()
    headers = {"origin": "http://localhost:3000"}
    for email in ["Person@example.com", " person@example.com "]:
        response = await client.post(
            "/api/v1/ipo-alerts/subscribe", json={"email": email, "consent": True}, headers=headers
        )
        assert response.status_code == 202
    assert await db.scalar(select(func.count()).select_from(m.EmailSubscriber)) == 1
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 1
    row = await db.scalar(select(m.EmailDelivery))
    value = token(row.id, "action")
    assert (
        await client.post("/api/v1/ipo-alerts/confirm", json={"token": value}, headers=headers)
    ).status_code == 200
    assert (
        await client.post("/api/v1/ipo-alerts/unsubscribe", json={"token": value}, headers=headers)
    ).status_code == 200
    await client.post("/api/v1/ipo-alerts/confirm", json={"token": value}, headers=headers)
    sub = await db.get(m.EmailSubscriber, row.subscriber_id)
    assert sub.unsubscribed_at is not None  # replay cannot re-subscribe


async def test_clicks_dedupe_unique_and_scanners(client, db):
    _, _, row = await alert(db)
    path = "/api/v1/ipo-alerts/click/" + token(row.id, "click")
    for agent in ["security scanner", "browser", "browser"]:
        response = await client.get(path, headers={"user-agent": agent}, follow_redirects=False)
        assert response.status_code == 302
        assert urlsplit(response.headers["location"]).netloc == "localhost:3000"
        assert "utm_source=meraipo_email" in response.headers["location"]
        assert response.headers["referrer-policy"] == "no-referrer"
    assert await db.scalar(select(func.count()).select_from(m.EmailClickEvent)) == 3
    assert row.clicked_at is not None
    assert (await client.get("/api/v1/ipo-alerts/click/" + "0" * 64)).status_code == 404


async def test_ses_events_idempotent_and_suppress(db):
    sub, _, row = await alert(db)
    stamp = m.now().isoformat()
    event = {
        "eventType": "Delivery",
        "mail": {"messageId": "ses-test", "timestamp": stamp, "tags": {"delivery_id": [row.id]}},
        "delivery": {"timestamp": stamp},
    }
    await ingest_event(db, "event-1", event)
    await db.commit()
    await ingest_event(db, "event-1", event)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(m.EmailDeliveryEvent)) == 1
    assert row.delivered_at is not None
    event["eventType"] = "Complaint"
    event["complaint"] = {"timestamp": stamp}
    await ingest_event(db, "event-2", event)
    await db.commit()
    assert sub.suppressed_at is not None
    with pytest.raises(HTTPException):
        await ingest_event(db, "bad", {"mail": {}})


async def test_admin_cohort_and_missing_ga4(admin_client, db):
    _, _, row = await alert(db)
    row.accepted_at = m.now()
    row.delivered_at = m.now()
    row.clicked_at = m.now()
    await db.commit()
    response = await admin_client.get("/api/v1/admin/email-analytics")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metrics"]["sent"] == data["metrics"]["delivered"] == 1
    assert data["metrics"]["click_rate"] == 100
    assert data["ga4"]["status"] == "NOT_CONNECTED"
    assert data["rows"][0]["sessions"] is None
    assert "email_encrypted" not in response.text and "a@example.com" not in response.text


async def test_anonymous_admin_denied(client):
    assert (await client.get("/api/v1/admin/email-analytics")).status_code in (401, 403)
    assert (await reports(date(2026, 1, 1), date(2026, 1, 2)))["status"] == "NOT_CONNECTED"


async def test_untrusted_sns_rejected_before_fetch(monkeypatch):
    monkeypatch.setattr(
        settings(), "ses_sns_topic_arn", "arn:aws:sns:ap-south-1:123456789012:email"
    )
    with pytest.raises(HTTPException):
        await verify_sns(
            {
                "TopicArn": settings().ses_sns_topic_arn,
                "SigningCertURL": "http://169.254.169.254/private",
            }
        )


async def test_schedule_dedup_and_send_idempotency(db, monkeypatch):
    sub, _, initial = await alert(db)
    ipo = await db.scalar(select(m.IPO))
    company = await db.get(m.Company, ipo.company_id)
    company.is_demo = False
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    from zoneinfo import ZoneInfo

    today = m.now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    dates.listing_date = today + timedelta(days=1)
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    guide.schedule_status = "CONFIRMED"
    guide.verification_status = "VERIFIED"
    from packages.shared.email_alerts import control

    state = await control(db)
    state.sending_enabled = True
    campaign = await db.get(m.EmailCampaign, initial.campaign_id)
    campaign.scheduled_date = today
    await db.commit()
    await prepare(db)
    await prepare(db)
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 1
    sends = []

    def fake_send(*args):
        sends.append(args)
        return "fake-message"

    monkeypatch.setattr("apps.worker.email_alerts.ses_send", fake_send)
    await send_one(db, initial.id, approved=True)
    await send_one(db, initial.id, approved=True)
    assert len(sends) == 1
    assert "utm_campaign=ipo_prelisting" in sends[0][2]
    assert initial.delivered_at is None  # SES acceptance is not delivery


async def test_sns_signature_valid_and_tampered(monkeypatch):
    import base64
    import json

    import httpx
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(m.now() - timedelta(days=1))
        .not_valid_after(m.now() + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    topic = "arn:aws:sns:ap-south-1:123456789012:email"
    monkeypatch.setattr(settings(), "ses_sns_topic_arn", topic)
    body = {
        "Type": "Notification",
        "Message": json.dumps({"eventType": "Delivery"}),
        "MessageId": "signed-event",
        "Timestamp": m.now().isoformat(),
        "TopicArn": topic,
        "SignatureVersion": "2",
        "SigningCertURL": "https://sns.ap-south-1.amazonaws.com/SimpleNotificationService-fixture.pem",
    }
    canonical = "".join(
        f"{field}\n{body[field]}\n"
        for field in ["Message", "MessageId", "Timestamp", "TopicArn", "Type"]
    ).encode()
    body["Signature"] = base64.b64encode(
        key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=cert.public_bytes(serialization.Encoding.PEM))
    )
    monkeypatch.setattr(
        "packages.providers.ses_events.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    assert await verify_sns(body) == {"eventType": "Delivery"}
    body["Message"] = '{"eventType":"Complaint"}'
    with pytest.raises(HTTPException):
        await verify_sns(body)

    # Signed subscription confirmation uses SNS API; it never follows SubscribeURL.
    body.update(
        Type="SubscriptionConfirmation",
        Token="signed-token",
        SubscribeURL="https://untrusted.invalid/never-fetch",
    )
    fields = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]

    def sign():
        raw = "".join(f"{field}\n{body[field]}\n" for field in fields).encode()
        body["Signature"] = base64.b64encode(
            key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        ).decode()

    sign()
    confirmed = []

    class SNS:
        def confirm_subscription(self, **kwargs):
            confirmed.append(kwargs)

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: SNS())
    assert await verify_sns(body) is None
    assert confirmed[0]["TopicArn"] == topic and confirmed[0]["Token"] == "signed-token"
    body["Timestamp"] = (m.now() - timedelta(hours=25)).isoformat()
    sign()
    with pytest.raises(HTTPException):
        await verify_sns(body)


def test_email_migration_roundtrip():
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    migration = importlib.import_module(
        "packages.database.migrations.versions.20261031_email_alerts"
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            assert "email_deliveries" in inspect(connection).get_table_names()
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()


def test_ses_payload_uses_supported_headers_and_safe_html(monkeypatch):
    from botocore.session import get_session
    from botocore.validate import validate_parameters

    from apps.worker.email_alerts import ses_send

    captured = {}

    class FakeSES:
        def send_email(self, **kwargs):
            validate_parameters(
                kwargs,
                get_session().get_service_model("sesv2").operation_model("SendEmail").input_shape,
            )
            captured.update(kwargs)
            return {"MessageId": "fixture-message"}

    monkeypatch.setattr("apps.worker.email_alerts.boto3.client", lambda *args, **kwargs: FakeSES())
    target = "http://localhost:3000/api/ipo-alerts/click/" + "a" * 64
    unsubscribe = "http://localhost:3000/api/ipo-alerts/unsubscribe/" + "b" * 64
    assert (
        ses_send(
            "person@example.com",
            "Reminder",
            "<unsafe> " + target + " https://external.invalid/",
            unsubscribe,
            "fixture-id",
        )
        == "fixture-message"
    )
    markup = captured["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "&lt;unsafe&gt;" in markup
    assert f'<a href="{target}">' in markup
    assert '<a href="https://external.invalid/' not in markup
    assert captured["Content"]["Simple"]["Headers"][1]["Value"] == "List-Unsubscribe=One-Click"


async def test_email_feature_gate_and_setup_requirement(admin_client, db, monkeypatch):
    response = await admin_client.post(
        "/api/v1/ipo-alerts/subscribe", json={"email": "off@example.com", "consent": True}
    )
    assert response.status_code == 404
    monkeypatch.setattr(settings(), "email_alerts_enabled", False)
    response = await admin_client.put("/api/v1/admin/features/email_alerts", json={"enabled": True})
    assert response.status_code == 409
    monkeypatch.setattr(settings(), "email_alerts_enabled", True)
    assert (
        await admin_client.put("/api/v1/admin/features/email_alerts", json={"enabled": True})
    ).status_code == 200
    assert (await db.get(m.FeatureFlag, "email_alerts")).enabled is True
    assert (
        await admin_client.put("/api/v1/admin/features/email_alerts", json={"enabled": False})
    ).status_code == 200
    assert not (await db.get(m.FeatureFlag, "email_alerts")).enabled


async def test_paused_feature_does_not_send_and_unsubscribe_stays_available(
    client, db, monkeypatch
):
    sub, _, row = await alert(db)
    flag = await db.get(m.FeatureFlag, "email_alerts")
    flag.enabled = False
    await db.commit()

    def unexpected(*args):
        raise AssertionError("Paused feature must not call SES")

    monkeypatch.setattr("apps.worker.email_alerts.ses_send", unexpected)
    await send_one(db, row.id)
    assert row.status == "PENDING"
    response = await client.post(
        "/api/v1/ipo-alerts/unsubscribe",
        json={"token": token(row.id, "action")},
        headers={"origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert sub.unsubscribed_at is not None


def test_opening_gmp_handles_zero_negative_missing_and_stale():
    from decimal import Decimal

    from apps.worker.email_alerts import opening_gmp

    assert "unavailable" in opening_gmp(None)
    row = m.GMP(value=Decimal("0"), observed_at=m.now(), source_provider="Test source")
    assert "₹0.00" in opening_gmp(row)
    assert "Latest recorded" in opening_gmp(row)
    assert "Test source" in opening_gmp(row) and "IST" in opening_gmp(row)
    row.value = Decimal("-10")
    row.observed_at = m.now() - timedelta(hours=settings().gmp_ttl_hours + 1)
    assert "₹-10.00" in opening_gmp(row) and "Stale" in opening_gmp(row)

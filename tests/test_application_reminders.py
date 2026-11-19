from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from packages.database import models as m
from packages.shared import email_digest, email_schedule
from packages.shared.config import settings
from packages.shared.email_alerts import control, token


@pytest.fixture
async def reminders(db, monkeypatch):
    now = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)  # 08:30 IST
    monkeypatch.setattr(m, "now", lambda: now)
    monkeypatch.setattr(
        settings(),
        "email_token_secret",
        SecretStr("application-test-secret-at-least-32-characters"),
    )
    rows = (
        await db.execute(
            select(m.IPO, m.IPODate, m.ApplicantGuide)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .join(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
            .limit(2)
        )
    ).all()
    assert len(rows) == 2
    for index, (ipo, dates, guide) in enumerate(rows):
        company = await db.get(m.Company, ipo.company_id)
        company.is_demo = False
        ipo.status, ipo.raw_status, ipo.price_high = "OPEN", "OPEN", 100
        dates.open_date = now.date() if index == 0 else now.date() - timedelta(days=2)
        dates.close_date = now.date() + timedelta(days=2) if index == 0 else now.date()
        guide.verification_status, guide.schedule_status = "VERIFIED", "CONFIRMED"
        db.add(
            m.GMP(
                ipo_id=ipo.id,
                value=30 if index == 0 else 150,
                observed_at=now,
                source_url="https://example.com/fixture",
                import_key=f"reminder-{index}",
            )
        )
    state = await control(db)
    state.application_schedule = {"mode": "both", "time": "08:30"}
    await db.commit()
    return rows, now.astimezone(email_schedule.IST)


async def test_modes_categories_and_closing_content(db, reminders):
    rows, now = reminders
    for mode, expected in (("opening", 1), ("closing", 1), ("both", 2)):
        payloads = await email_digest.build_payloads(db, rows, now, {"mode": mode, "time": "08:30"})
        assert len(payloads["white"]["ipo_ids"]) == expected
        assert len(payloads["light_green"]["ipo_ids"]) == expected
        assert len(payloads["gold"]["ipo_ids"]) == (0 if mode == "opening" else 1)
        if mode != "opening":
            assert "Closes Today" in payloads["white"]["text"]
            assert "Closing date: 2026-11-19" in payloads["white"]["text"]
    ipo, dates, guide = rows[0]
    dates.close_date = now.date()
    assert email_schedule.occasion(ipo, dates, guide, now.date(), "both") == "opening_closing"
    guide.verification_status = "UNVERIFIED"
    assert email_schedule.occasion(ipo, dates, guide, now.date(), "both") is None


def test_minute_schedule_window():
    config = {"mode": "both", "time": "08:30"}
    now = datetime(2026, 11, 19, 8, 29, tzinfo=email_schedule.IST)
    assert not email_schedule.in_window(config, now)
    assert email_schedule.in_window(config, now + timedelta(minutes=1))
    assert not email_schedule.in_window(config, now + timedelta(hours=5))


async def test_worker_at_0830_sends_again_only_on_closing_date(db, reminders, monkeypatch):
    from apps.worker.email_alerts import prepare

    _, now = reminders
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    db.add(
        m.EmailSubscriber(
            email_hash="two-days",
            email_encrypted="not-used-by-queue",
            consent_at=m.now(),
            verified_at=m.now(),
            gmp_band="white",
        )
    )
    await db.commit()
    monkeypatch.setattr(m, "now", lambda: now - timedelta(minutes=1))
    await prepare(db)
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 0
    monkeypatch.setattr(m, "now", lambda: now)
    await prepare(db)
    await prepare(db)
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 1
    monkeypatch.setattr(m, "now", lambda: now + timedelta(days=1))
    await prepare(db)
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 1
    monkeypatch.setattr(m, "now", lambda: now + timedelta(days=2))
    await prepare(db)
    await prepare(db)
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 2


async def test_thousand_recipients_render_once_and_resume(db, reminders, monkeypatch):
    rows, now = reminders
    db.add_all(
        [
            m.EmailSubscriber(
                email_hash=f"scale-reminder-{i}",
                email_encrypted="unused-in-scheduling",
                consent_at=m.now(),
                verified_at=m.now(),
                gmp_band="white",
            )
            for i in range(1000)
        ]
    )
    await db.commit()
    render = AsyncMock(wraps=email_digest.content)
    monkeypatch.setattr(email_digest, "content", render)
    for _ in range(6):
        await email_digest.prepare_digests(db, rows, now)
    assert render.await_count == 2  # once per IPO, not per category or recipient
    assert (
        await db.scalar(
            select(func.count())
            .select_from(m.EmailCampaign)
            .where(m.EmailCampaign.digest_key.is_not(None))
        )
        == 4
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(m.EmailDelivery)
            .where(m.EmailDelivery.digest_date == now.date())
        )
        == 1000
    )
    # The following day must not resend yesterday's campaign.
    subscriber = await db.scalar(
        select(m.EmailSubscriber).where(m.EmailSubscriber.email_hash == "scale-reminder-0")
    )
    campaign = await db.scalar(
        select(m.EmailCampaign).where(m.EmailCampaign.kind == "digest_white")
    )
    monkeypatch.setattr(m, "now", lambda: now + timedelta(days=1))
    assert not await email_digest.digest_is_current(db, campaign, subscriber)


async def test_fixed_recipient_full_outbox_and_preferences_unchanged(
    admin_client, db, reminders, monkeypatch
):
    from apps.api import email_admin
    from apps.worker import email_alerts
    from packages.shared.market_config import encrypt_secret

    monkeypatch.setattr(email_admin, "require_test_sender", AsyncMock())
    address = "meshanti.singh@gmail.com"
    sub = m.EmailSubscriber(
        email_hash=token(address, "email"),
        email_encrypted=encrypt_secret(address),
        consent_at=m.now(),
        verified_at=m.now(),
        gmp_band="gold",
    )
    db.add(sub)
    await db.commit()
    response = await admin_client.post("/api/v1/admin/email/application-test")
    assert response.status_code == 202, response.text
    key = response.json()["id"]
    row = await db.get(m.EmailDelivery, key)
    campaign = await db.get(m.EmailCampaign, row.campaign_id)
    assert row.kind == "TEST" and row.digest_date is None
    assert len(campaign.digest_payload["ipo_ids"]) == 2
    assert sub.gmp_band == "gold"  # test does not alter subscription
    sent = []

    def send(*args):
        sent.append(args)
        return "test-provider-message-id"

    monkeypatch.setattr(email_alerts, "ses_send", send)
    await email_alerts.send_one(db, key)
    await email_alerts.send_one(db, key)
    assert len(sent) == 1 and sent[0][0] == address
    assert "TEST" in sent[0][1] and "Closes Today" in sent[0][2]
    assert email_digest.UNSUBSCRIBE not in sent[0][2]
    result = await admin_client.get("/api/v1/admin/email/application-test/" + key)
    assert result.json()["status"] == "ACCEPTED"
    assert (await admin_client.post("/api/v1/admin/email/application-test")).status_code == 429


async def test_schedule_validation_and_no_automatic_enable(admin_client, db):
    assert (
        await admin_client.put(
            "/api/v1/admin/email/application-schedule", json={"mode": "both", "time": "08:30"}
        )
    ).status_code == 200
    assert await email_schedule.load(db) == {"mode": "both", "time": "08:30"}
    assert not (await control(db)).sending_enabled
    assert (
        await admin_client.put(
            "/api/v1/admin/email/application-schedule", json={"mode": "daily", "time": "25:00"}
        )
    ).status_code == 422


def test_application_schedule_migration_preserves_enable_flag():
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module(
        "packages.database.migrations.versions.20261119_email_schedule"
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE email_control (id VARCHAR(20) PRIMARY KEY, sending_enabled BOOLEAN NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO email_control VALUES ('email', 0)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(
                sa.text("SELECT sending_enabled, application_schedule FROM email_control")
            ).one() == (0, "{}")
            migration.downgrade()
            assert (
                connection.execute(sa.text("SELECT sending_enabled FROM email_control")).scalar()
                == 0
            )
    engine.dispose()

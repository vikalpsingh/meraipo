from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from packages.shared.email_reminders import reminder_week

IST = ZoneInfo("Asia/Kolkata")


def test_three_mondays_then_stop():
    created = datetime(2026, 11, 14, 10, tzinfo=IST)
    first = datetime(2026, 11, 16, 9, tzinfo=IST)
    assert reminder_week(created, first - timedelta(minutes=1)) is None
    for week in range(3):
        now = first + timedelta(weeks=week)
        assert reminder_week(created, now) == now.date()
    assert reminder_week(created, first + timedelta(weeks=3)) is None


def test_monday_after_nine_starts_next_week():
    created = datetime(2026, 11, 16, 10, tzinfo=IST)
    assert reminder_week(created, created) is None
    assert reminder_week(created, datetime(2026, 11, 23, 9, tzinfo=IST)).isoformat() == "2026-11-23"


async def test_bulk_idempotent_and_pending_only(db, monkeypatch):
    import json

    from pydantic import SecretStr
    from sqlalchemy import select

    from packages.database import models as m
    from packages.shared.config import settings
    from packages.shared.email_alerts import delivery
    from packages.shared.email_reminders import queue_reminders
    from packages.shared.market_config import encrypt_secret

    monkeypatch.setattr(
        settings(), "email_token_secret", SecretStr("test-reminder-secret-at-least-32-characters")
    )
    now = datetime(2026, 11, 16, 9, tzinfo=IST)
    monkeypatch.setattr(m, "now", lambda: now)
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    pending = m.EmailSubscriber(
        email_hash="reminder-test",
        email_encrypted=encrypt_secret("pending@example.com"),
        consent_at=now,
        created_at=now - timedelta(days=2),
    )
    db.add(pending)
    await db.flush()
    original = delivery(pending.id)
    original.created_at = now - timedelta(days=2)
    original.requested_profile_encrypted = encrypt_secret(
        json.dumps({"first_name": "Test", "last_name": "User", "gmp_band": "gold"})
    )
    db.add(original)
    await db.commit()
    assert (await queue_reminders(db))["queued"] == 1
    assert (await queue_reminders(db))["queued"] == 0
    pending.verified_at = now
    await db.commit()
    monkeypatch.setattr(m, "now", lambda: now + timedelta(weeks=1))
    assert (await queue_reminders(db))["queued"] == 0
    rows = (
        await db.scalars(select(m.EmailDelivery).where(m.EmailDelivery.reminder_week.is_not(None)))
    ).all()
    assert (
        len(rows) == 1
        and rows[0].requested_profile_encrypted == original.requested_profile_encrypted
    )

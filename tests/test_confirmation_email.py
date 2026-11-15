from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from packages.database import models as m
from packages.shared.confirmation_email import confirmation_content
from packages.shared.email_alerts import token_expired


def test_confirmation_template():
    subject, text, html = confirmation_content("https://www.meraipo.com", "abc", "gold")
    assert "confirm" in subject
    assert "Above 100%" in text and "Above 100%" in html
    assert "7 days" in text and "7 days" in html
    assert "meraipo-logo-market-header.png" in html
    assert "/email-alerts/verify#abc" in html
    assert "/email-alerts/unsubscribe#abc" in html
    assert "No unrelated promotions" in html
    assert "Reminder:" in confirmation_content("https://www.meraipo.com", "abc", reminder=True)[0]


def test_confirmation_expires_at_seven_days(monkeypatch):
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(m, "now", lambda: now)
    assert not token_expired(SimpleNamespace(created_at=now - timedelta(days=1)))
    assert not token_expired(
        SimpleNamespace(created_at=now - timedelta(days=7) + timedelta(seconds=1))
    )
    assert token_expired(SimpleNamespace(created_at=now - timedelta(days=7)))

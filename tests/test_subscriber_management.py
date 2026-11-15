import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import SecretStr
from sqlalchemy import func, select

from apps.api.email_admin import SubscriberEdit, delete_subscriber, edit_subscriber
from apps.api.email_routes import subscribe
from packages.database import models as m
from packages.shared.config import settings
from packages.shared.email_alerts import normalized_email, token
from packages.shared.email_brokers import broker_content
from packages.shared.market_config import decrypt_secret, encrypt_secret


def test_case_insensitive_email_and_broker_allowlist():
    assert normalized_email("  User@Example.COM ") == "user@example.com"
    assert "https://kite.zerodha.com/" in broker_content("zerodha")[1]
    assert broker_content("other") == ("", "")
    assert broker_content("https://evil.example") == ("", "")


async def test_active_override_and_admin_management(db, monkeypatch):
    config = settings()
    monkeypatch.setattr(
        config, "email_token_secret", SecretStr("test-subscription-unique-key-32-characters")
    )
    monkeypatch.setattr(config, "email_from", "alerts@meraipo.com")
    monkeypatch.setattr("apps.api.email_routes.throttle", AsyncMock())
    db.add(m.FeatureFlag(key="email_alerts", enabled=True))
    sub = m.EmailSubscriber(
        email_hash=token("user@example.com", "email"),
        email_encrypted=encrypt_secret("user@example.com"),
        consent_at=m.now(),
        verified_at=m.now(),
        gmp_band="gold",
    )
    db.add(sub)
    await db.commit()
    body = dict(
        email="USER@EXAMPLE.COM",
        first_name="First",
        last_name="Last",
        gmp_band="white",
        broker="groww",
        consent=True,
    )
    request = SimpleNamespace(
        headers={"origin": config.public_origin}, json=AsyncMock(return_value=body)
    )
    response = await subscribe(request, db)
    assert response.status_code == 409
    assert sub.gmp_band == "gold"
    body["confirm_override"] = True
    response = await subscribe(request, db)
    assert response.status_code == 202
    assert await db.scalar(select(func.count()).select_from(m.EmailSubscriber)) == 1
    row = await db.scalar(select(m.EmailDelivery).where(m.EmailDelivery.subscriber_id == sub.id))
    assert json.loads(decrypt_secret(row.requested_profile_encrypted))["broker"] == "groww"
    await edit_subscriber(
        sub.id,
        SubscriberEdit(
            first_name="Updated", last_name="Name", gmp_band="light_green", broker="upstox"
        ),
        (SimpleNamespace(id=None),),
        db,
    )
    assert sub.gmp_band == "light_green"
    assert json.loads(decrypt_secret(sub.contact_encrypted))["broker"] == "upstox"
    await delete_subscriber(sub.id, (SimpleNamespace(id=None),), db)
    assert await db.scalar(select(func.count()).select_from(m.EmailSubscriber)) == 0
    assert await db.scalar(select(func.count()).select_from(m.EmailDelivery)) == 0

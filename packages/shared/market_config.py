"""Database-backed market settings with encrypted provider credentials."""

import base64
import hashlib
from contextlib import asynccontextmanager

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from packages.database import models as m
from packages.shared.config import Settings, base_settings, use_settings

CONFIG_ID = "market"
EDITABLE_FIELDS = (
    "provider_mode",
    "market_scheduler_enabled",
    "market_scheduler_driver",
    "exchange_direct_enabled",
    "nse_subscription_categories_enabled",
    "ipo_data_provider",
    "ipoalerts_page_size",
    "exchange_sources_json",
    "bse_ipo_issues_json",
    "trading_holidays",
    "trading_calendar_year",
)


def _cipher() -> Fernet:
    base = base_settings()
    material = base.config_encryption_key.get_secret_value() or base.cron_secret
    if len(material) < 32:
        raise ValueError(
            "Set CONFIG_ENCRYPTION_KEY (at least 32 characters) before saving API keys"
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored API key cannot be decrypted with CONFIG_ENCRYPTION_KEY") from exc


async def load_market_settings(db) -> Settings:
    base = base_settings()
    row = await db.get(m.MarketConfiguration, CONFIG_ID)
    if not row:
        return base
    updates = {key: value for key, value in (row.values or {}).items() if key in EDITABLE_FIELDS}
    if row.ipoalerts_api_key_encrypted:
        updates["ipoalerts_api_key"] = SecretStr(decrypt_secret(row.ipoalerts_api_key_encrypted))
    if row.market_feeds_json_encrypted:
        updates["market_feeds_json"] = decrypt_secret(row.market_feeds_json_encrypted)
    return Settings.model_validate({**base.model_dump(), **updates})


@asynccontextmanager
async def market_settings_context(db):
    effective = await load_market_settings(db)
    with use_settings(effective):
        yield effective

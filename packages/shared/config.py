from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://meraipo:meraipo@localhost:5432/meraipo"
    redis_url: str = "redis://localhost:6379/0"
    public_origin: str = "http://localhost:3000"
    demo_mode: bool = False
    session_hours: int = 8
    cache_ttl: int = 60
    gmp_ttl_hours: int = 12
    price_ttl_hours: int = 72
    storage_backend: str = "local"
    storage_path: str = "./work/documents"
    s3_bucket: str = ""
    s3_endpoint: str | None = None
    provider_mode: str = "manual"
    ipo_refresh_minutes: int = 240
    results_refresh_minutes: int = 1440
    document_refresh_minutes: int = 1440
    gmp_refresh_minutes: int = 60
    eod_hour_ist: int = 18
    cron_secret: str = ""
    market_feeds_json: str = "{}"
    trading_holidays: str = ""
    trading_calendar_year: int = 0
    market_scheduler_enabled: bool = False
    exchange_direct_enabled: bool = False
    exchange_sources_json: str = "[]"
    market_scheduler_driver: Literal["celery", "vercel"] = "celery"

    @model_validator(mode="after")
    def production_configuration(self):
        if self.environment == "production":
            if self.demo_mode or not self.public_origin.startswith("https://"):
                raise ValueError("Production requires HTTPS and demo_mode=false")
            if not self.database_url.startswith("postgresql+") or any(
                value in self.database_url for value in (":meraipo@", ":local-development-only@")
            ):
                raise ValueError("Production requires PostgreSQL with non-default credentials")
            if not self.redis_url:
                raise ValueError("Production requires shared Redis")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()

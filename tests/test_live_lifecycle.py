from datetime import UTC, date, datetime

from sqlalchemy import select

from apps.api.main import read_catalog
from apps.api.repository import catalog
from packages.database import models as m
from packages.shared.config import settings


async def test_public_status_crosses_ist_midnight_without_scheduler_write(db, monkeypatch):
    company = m.Company(
        slug="midnight-fixture", name="Midnight Fixture", board="Mainboard", is_demo=False
    )
    db.add(company)
    await db.flush()
    ipo = m.IPO(
        company_id=company.id, status="OPEN", raw_status="OPEN", source_provider="IPOALERTS"
    )
    db.add(ipo)
    await db.flush()
    db.add(
        m.IPODate(
            ipo_id=ipo.id,
            open_date=date(2026, 9, 20),
            close_date=date(2026, 9, 21),
            listing_date=date(2026, 9, 24),
        )
    )
    await db.flush()

    def fixture(rows):
        return next(c for c in rows if c["slug"] == "midnight-fixture")

    monkeypatch.setattr(m, "now", lambda: datetime(2026, 9, 21, 18, 29, 59, tzinfo=UTC))
    assert fixture(await catalog(db))["status"] == "OPEN"
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 9, 21, 18, 30, tzinfo=UTC))
    assert fixture(await catalog(db))["status"] == "CLOSED"
    assert (await db.scalar(select(m.IPO).where(m.IPO.id == ipo.id))).status == "OPEN"
    assert fixture(await catalog(db, date(2026, 9, 24)))["status"] == "LISTED"
    assert fixture(await catalog(db, date(2026, 9, 19)))["status"] == "UPCOMING"


async def test_public_cache_key_changes_on_india_date_boundary(db, monkeypatch):
    from apps.api import cache

    keys = []

    async def capture(key, loader):
        keys.append(key)
        return await loader()

    monkeypatch.setattr(settings(), "environment", "development")
    monkeypatch.setattr(cache, "cached", capture)
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 9, 21, 18, 29, 59, tzinfo=UTC))
    await read_catalog(db)
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 9, 21, 18, 30, tzinfo=UTC))
    await read_catalog(db)
    assert keys == ["catalog:2026-09-21", "catalog:2026-09-22"]

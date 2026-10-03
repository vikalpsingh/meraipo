from datetime import date, timedelta

import pytest
from sqlalchemy import select

from apps.api import analytics_routes as analytics
from packages.database.models import ClickDaily


@pytest.fixture(autouse=True)
def analytics_clock(monkeypatch):
    monkeypatch.setattr(analytics, "today_ist", lambda: date(2026, 10, 3))

    async def allowed(*args):
        return 1

    monkeypatch.setattr(analytics.client, "eval", allowed)


async def test_click_ingestion_is_additive_and_bounded(client, db):
    headers = {"origin": "http://localhost:3000"}
    for count in (2, 3):
        response = await client.post(
            "/api/v1/analytics/clicks", json={"section": "home", "count": count}, headers=headers
        )
        assert response.status_code == 204
    row = await db.scalar(select(ClickDaily))
    assert row.clicks == 5 and row.day == date(2026, 10, 3)
    for payload in (
        {"section": "arbitrary-url", "count": 1},
        {"section": "home", "count": 101},
        {"section": "home", "count": True},
        {"section": "home", "count": 0},
    ):
        assert (
            await client.post("/api/v1/analytics/clicks", json=payload, headers=headers)
        ).status_code == 422
    assert (
        await client.post("/api/v1/analytics/clicks", json={"section": "home", "count": 1})
    ).status_code == 403
    assert (await client.get("/api/v1/admin/analytics")).status_code == 401


async def test_calendar_totals_and_retention(admin_client, db):
    today = date(2026, 10, 3)
    for day, clicks in [
        (today, 2),
        (date(2026, 10, 1), 3),
        (date(2026, 9, 28), 5),
        (date(2026, 9, 27), 7),
        (today - timedelta(days=400), 999),
    ]:
        db.add(ClickDaily(day=day, section="home", clicks=clicks))
    await db.commit()
    response = await admin_client.get("/api/v1/admin/analytics")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["totals"] == {"today": 2, "week": 10, "month": 5}
    assert len(response.json()["daily"]) == 4
    assert len((await db.scalars(select(ClickDaily))).all()) == 4


async def test_rate_limit_does_not_write(client, db, monkeypatch):
    async def limited(*args):
        return 3001

    monkeypatch.setattr(analytics.client, "eval", limited)
    response = await client.post(
        "/api/v1/analytics/clicks",
        json={"section": "home", "count": 1},
        headers={"origin": "http://localhost:3000"},
    )
    assert response.status_code == 429
    assert await db.scalar(select(ClickDaily)) is None

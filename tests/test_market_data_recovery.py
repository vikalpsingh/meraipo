"""Regression coverage for missing enrichment and non-trading-day price recovery."""

import time
from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import journey
from apps.worker.exchange_pipeline import latest_trading_day, run_pipeline
from apps.worker.market import create_run
from packages.database import models as m
from packages.providers import exchanges as ex
from packages.providers.ipoalerts import IPOAlerts, normalize_gmp
from packages.providers.market import FeedError
from packages.shared.config import settings
from tests.test_exchange_pipeline import CSV, DAY
from tests.test_ipoalerts import no_sleep, response, row
from tests.test_market_integration import tracked


@pytest.mark.parametrize(
    ("requested", "holidays", "expected"),
    [
        ("2026-07-25", "", "2026-07-24"),
        ("2026-07-26", "", "2026-07-24"),
        ("2026-07-27", "2026-07-27,2026-07-24", "2026-07-23"),
        ("2026-07-24", "", "2026-07-24"),
    ],
)
def test_latest_trading_date(requested, holidays, expected):
    config = SimpleNamespace(trading_calendar_year=2026, trading_holidays=holidays)
    assert latest_trading_day(date.fromisoformat(requested), config).isoformat() == expected


def test_calendar_rollover_requires_verified_previous_year():
    config = SimpleNamespace(trading_calendar_year=2026, trading_holidays="2026-01-01")
    with pytest.raises(FeedError, match="TRADING_CALENDAR_REQUIRED"):
        latest_trading_day(date(2026, 1, 1), config)


def test_future_date_rejected(monkeypatch):
    monkeypatch.setattr("apps.worker.exchange_pipeline.india_today", lambda: date(2026, 7, 24))
    with pytest.raises(FeedError, match="FUTURE_TRADE_DATE"):
        latest_trading_day(
            date(2026, 7, 27), SimpleNamespace(trading_calendar_year=2026, trading_holidays="")
        )


def test_daily_price_schedule_includes_weekend():
    from zoneinfo import ZoneInfo

    from packages.shared.market_freshness import next_scheduled

    at = datetime(2026, 7, 25, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert next_scheduled("sync-prices", at).startswith("2026-07-25T23:10")


@pytest.mark.parametrize("value", [0, -2.5, 13.5])
def test_gmp_zero_negative_and_timestamp(value):
    item = row(gmp={"aggregations": {"mean": value}, "lastUpdatedAt": "2026-07-24T12:00:00Z"})
    data = normalize_gmp(item)
    assert float(data["value"]) == value
    assert data["source_timestamp"] == "2026-07-24T12:00:00Z"
    assert data["provider_id"] == item["id"]


@pytest.mark.parametrize("gmp", [None, {}, {"sources": []}, {"aggregations": {"mean": None}}])
def test_missing_gmp_is_not_zero(gmp):
    assert normalize_gmp(row(gmp=gmp)) is None


async def test_gmp_full_pipeline_and_repeat_preserve_timestamp(db, monkeypatch):
    from packages.providers import ipo as registry

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    item = row(gmp={"aggregations": {"mean": 13.5}, "lastUpdatedAt": "2026-07-24T12:00:00Z"})

    def handle(request):
        assert request.url.params["includeGmp"] == "true"
        return httpx.Response(
            200, json=response([item] if request.url.params["status"] == "open" else [])
        )

    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts("test", transport=httpx.MockTransport(handle), sleep=no_sleep),
    )
    for _ in range(2):
        run = await create_run(db, "sync-ipos", "manual")
        await run_pipeline(db, run)
        assert run.status == "SUCCESS", run.counters
    public = await journey(db, "provider-fixture")
    assert public["gmp"] == 13.5
    assert public["gmp_timestamp"].startswith("2026-07-24")
    assert (
        await db.scalar(
            select(func.count()).select_from(m.GMP).where(m.GMP.ipo_id == public["ipo_id"])
        )
        == 1
    )
    assert (
        await db.scalar(select(m.MarketStage.authority).where(m.MarketStage.kind == "gmp"))
        == "UNOFFICIAL"
    )


async def test_invalid_gmp_does_not_drop_ipo():
    item = row(gmp={"aggregations": {"mean": "invalid"}, "lastUpdatedAt": "bad"})
    adapter = IPOAlerts(
        "test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=response([item] if request.url.params["status"] == "open" else [])
            )
        ),
        sleep=no_sleep,
    )
    batches = [batch async for batch in adapter.batches(time.monotonic() + 30)]
    assert batches[0].records[0][0] == "ipos"
    assert batches[0].errors == [("gmp:fixture-123", "IPOALERTS_INVALID_GMP")]


async def test_holiday_job_populates_last_trading_date_and_is_idempotent(db, monkeypatch):
    await tracked(db, "LISTED")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(settings(), "trading_calendar_year", DAY.year)
    monkeypatch.setattr(settings(), "trading_holidays", "2026-07-21")
    monkeypatch.setattr("apps.worker.exchange_pipeline.india_today", lambda: date(2026, 7, 21))
    seen = []

    async def download(url):
        seen.append(url)
        assert f"{DAY:%Y%m%d}" in url
        return CSV

    for _ in range(2):
        run = await create_run(db, "sync-prices", "manual")
        await run_pipeline(db, run, download)
        assert run.status == "SUCCESS", run.error
        assert run.parameters["resolved_trade_date"] == DAY.isoformat()
    public = await journey(db, "real-fixture")
    assert public["cmp"] == 125
    assert str(public["price_date"]) == DAY.isoformat()
    assert (
        await db.scalar(
            select(func.count()).select_from(m.Price).where(m.Price.company_id == public["id"])
        )
        == 1
    )
    assert len(seen) == 4


def test_bse_symbol_maps_price_without_existing_scrip_code():
    identities = {"isin": set(), "NSE": set(), "BSE": set(), "BSE_SYMBOL": {"EXAMPLE"}}
    # Same official UDiFF schema; exact symbol, never issuer-name matching.
    content = CSV.replace(b"TRACKED", b"EXAMPLE")
    _, records, errors = ex.parse_bhavcopy(content, "BSE", DAY, identities, datetime.now(UTC))
    assert not errors
    assert records, content
    assert records[0][1]["bse_symbol"] == "EXAMPLE"


async def test_subscription_categories_collect_with_ipoalerts_master(db, monkeypatch):
    from packages.providers import ipo as registry

    await tracked(db)
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(
        settings(), "bse_ipo_issues_json", '[{"issue_id":"7154","isin":"INE000A01010"}]'
    )
    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts(
            "test",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response([]))),
            sleep=no_sleep,
        ),
    )

    async def download(url):
        if url == ex.NSE_IPO:
            return b"[]"
        assert "CummDemandSchedule" in url
        return b"<h1>Cumulative Demand Schedule</h1><table><tr><th>Category</th><th>Shares offered</th><th>Shares bid</th></tr><tr><td>Retail</td><td>1000</td><td>2500</td></tr><tr><td>QIB</td><td>2000</td><td>0</td></tr><tr><td>NII</td><td>1000</td><td>1500</td></tr><tr><td>Total</td><td>4000</td><td>4000</td></tr></table>"

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.counters
    public = await journey(db, "real-fixture")
    assert float(public["subscription"]["categories"]["retail"]["multiple"]) == 2.5
    assert float(public["subscription"]["categories"]["qib"]["multiple"]) == 0
    assert float(public["subscription"]["categories"]["nii"]["multiple"]) == 1.5
    assert public["subscription"]["multiple"] == 1
    assert await db.scalar(select(func.count()).select_from(m.SubscriptionDay)) == 1


async def test_nse_totals_survive_provider_switch_without_overwriting_master(db, monkeypatch):
    from packages.providers import ipo as registry
    from tests.test_exchange_pipeline import ipo_body

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    item = row()
    item["symbol"] = "EXAMPLE"
    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts(
            "test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=response([item] if request.url.params["status"] == "open" else [])
                )
            ),
            sleep=no_sleep,
        ),
    )

    async def download(url):
        assert url == ex.NSE_IPO
        return ipo_body()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    public = await journey(db, "provider-fixture")
    assert public["subscription"]["multiple"] == 2.5
    assert public["price_high"] == 99  # Exchange metadata must not override the chosen provider.
    assert public["subscription"]["categories"]["retail"]["multiple"] is None
    assert public["subscription"]["categories"]["retail"]["gap_note"]
    assert (
        await db.scalar(select(m.JobError.code).where(m.JobError.run_id == run.id))
        == "SUBSCRIPTION_CATEGORIES_NOT_CONFIGURED"
    )

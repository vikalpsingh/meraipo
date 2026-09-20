import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import journey
from apps.worker.market import acquire, create_run, ingest_record, lifecycle, run_job
from packages.database import models as m
from packages.providers.market import (
    Eod,
    FeedConfig,
    FeedError,
    Financial,
    Premium,
    fetch_feed,
)
from packages.providers.xbrl import parse_instance
from packages.shared.config import settings


def observation(**values):
    return {
        "isin": "INE000A01010",
        "source_url": "https://exchange.example/filing",
        "source_timestamp": "2026-07-20T10:00:00Z",
        **values,
    }


async def tracked(db, status="OPEN"):
    company = m.Company(
        slug="real-fixture", name="Tracked fixture", isin="INE000A01010", is_demo=False
    )
    db.add(company)
    await db.flush()
    ipo = m.IPO(company_id=company.id, status=status, price_high=100, issue_price=100, lot_size=100)
    db.add(ipo)
    await db.commit()
    return company, ipo


def configured(monkeypatch, *kinds):
    monkeypatch.setattr(
        settings(),
        "market_feeds_json",
        json.dumps(
            {
                kind: {
                    "fixture-feed": {
                        "url": "https://feed.example/v1",
                        "authority": (
                            "UNOFFICIAL"
                            if kind == "gmp"
                            else "LICENSED" if kind == "prices" else "NSE"
                        ),
                        "enabled": True,
                    }
                }
                for kind in kinds
            }
        ),
    )


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 7, 1), "UPCOMING"),
        (date(2026, 7, 10), "OPEN"),
        (date(2026, 7, 13), "ALLOTMENT_PENDING"),
        (date(2026, 7, 14), "ALLOTMENT_COMPLETED"),
        (date(2026, 7, 16), "LISTING_TODAY"),
        (date(2026, 7, 17), "LISTED"),
    ],
)
def test_ist_lifecycle(day, expected):
    dates = SimpleNamespace(
        open_date=date(2026, 7, 10),
        close_date=date(2026, 7, 12),
        listing_date=date(2026, 7, 16),
        allotment_date=None,
    )
    guide = SimpleNamespace(schedule_status="CONFIRMED", allotment_date=date(2026, 7, 14))
    assert lifecycle(SimpleNamespace(raw_status="OPEN"), dates, guide, day) == expected
    assert lifecycle(SimpleNamespace(raw_status="WITHDRAWN"), dates, guide, day) == "WITHDRAWN"


async def test_no_open_skips_before_provider(db, monkeypatch):
    configured(monkeypatch, "subscriptions", "gmp")

    async def forbidden(*args):
        pytest.fail("Must not call external feed with no open non-demo IPO")

    run = await create_run(db, "ipo-live", "scheduled")
    result = await run_job(db, run, forbidden)
    assert result.status == "SKIPPED"
    assert "NO_OPEN_IPOS" in result.error


async def test_snapshot_dedup_and_item_isolation(db, monkeypatch):
    _, ipo = await tracked(db)
    configured(monkeypatch, "subscriptions")
    good = observation(categories={"retail": {"multiple": "2.5"}, "total": {"multiple": "3"}})

    async def feed(*args):
        records = [good, {**good, "categories": {"retail": {"multiple": "-1"}}}]
        return json.dumps(records), records

    for _ in range(2):
        run = await create_run(db, "ipo-live", "manual")
        await run_job(db, run, feed)
        assert run.status == "PARTIAL"
        assert run.counters["failed"] == 1
    assert (
        await db.scalar(
            select(func.count()).select_from(m.Subscription).where(m.Subscription.ipo_id == ipo.id)
        )
        == 1
    )
    assert await db.scalar(select(func.count()).select_from(m.RawPayload)) == 2
    assert await db.scalar(select(func.count()).select_from(m.JobError)) == 2


async def test_gmp_and_eod_retain_history(db):
    company, ipo = await tracked(db, "LISTED")
    data = Premium.model_validate(observation(value="15"))
    assert await ingest_record(db, "gmp", data, "licensed-gmp", "UNOFFICIAL", None)
    assert not await ingest_record(db, "gmp", data, "licensed-gmp", "UNOFFICIAL", None)
    price = Eod.model_validate(
        observation(price_date="2026-07-20", close="130", high="135", low="125", volume="10000")
    )
    await ingest_record(db, "prices", price, "eod", "LICENSED", None)
    await ingest_record(db, "prices", price, "eod", "LICENSED", None)
    await db.commit()
    assert (
        await db.scalar(
            select(func.count()).select_from(m.Price).where(m.Price.company_id == company.id)
        )
        == 1
    )
    page = await journey(db, company.slug)
    assert page["return_ipo"] == 30
    assert page["gmp_estimated_price"] == 115


def financial(**changes):
    return Financial.model_validate(
        observation(
            financial_year=2027,
            quarter=1,
            period_type="QUARTERLY",
            statement_type="CONSOLIDATED",
            period_start="2026-04-01",
            period_end="2026-06-30",
            filing_id="filing-1",
            revenue="100",
            pat="10",
            **changes,
        )
    )


async def test_revisions_consolidated_and_safe_comparisons(db):
    company, _ = await tracked(db, "LISTED")
    data = financial()
    await ingest_record(db, "results", data, "NSE", "NSE", None)
    assert not await ingest_record(db, "results", data, "NSE", "NSE", None)
    revised = data.model_copy(
        update={
            "revenue": Decimal("120"),
            "filing_id": "filing-2",
            "source_timestamp": data.source_timestamp,  # amendments can retain a filing timestamp
        }
    )
    await ingest_record(db, "results", revised, "NSE", "NSE", None)
    standalone = revised.model_copy(
        update={"statement_type": "STANDALONE", "revenue": Decimal("80"), "filing_id": "filing-3"}
    )
    await ingest_record(db, "results", standalone, "NSE", "NSE", None)
    await db.commit()
    page = await journey(db, company.slug)
    assert page["latest"]["revenue"] == 120
    assert page["latest"]["revenue_qoq"] is None
    assert page["latest"]["revenue_yoy"] is None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(m.Quarterly)
            .where(m.Quarterly.company_id == company.id)
        )
        == 3
    )


async def test_annual_history_four_years_and_revisions(db):
    company, _ = await tracked(db, "LISTED")
    for year in range(2021, 2027):
        data = Financial.model_validate(
            observation(
                financial_year=year,
                period_type="ANNUAL",
                statement_type="CONSOLIDATED",
                period_start=f"{year-1}-04-01",
                period_end=f"{year}-03-31",
                filing_id=f"annual-{year}",
                revenue="100",
            )
        )
        await ingest_record(db, "results", data, "NSE", "NSE", None)
    await db.commit()
    page = await journey(db, company.slug)
    assert [r["financial_year"] for r in page["annuals"]] == [2026, 2025, 2024, 2023]


async def test_lock_expiry_and_overlap(db):
    assert await acquire(db, "first")
    await db.commit()
    assert not await acquire(db, "second")
    lock = await db.get(m.JobLock, "market-writer")
    lock.expires_at = m.now() - timedelta(seconds=1)
    await db.commit()
    assert await acquire(db, "second")


async def test_feed_retry_and_no_credentials_in_errors():
    attempts = []

    async def respond(request):
        attempts.append(request)
        return httpx.Response(
            429 if len(attempts) == 1 else 200,
            json={"schema": "meraipo-feed-v1", "records": []},
            headers={"Retry-After": "0"},
        )

    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    config = FeedConfig(
        url="https://feed.example/v1", token="top-secret", enabled=True, authority="NSE"
    )
    await fetch_feed(config, {}, httpx.MockTransport(respond), sleep)
    assert len(attempts) == 2 and len(waits) == 1
    with pytest.raises(FeedError, match="HTTP_403"):
        await fetch_feed(config, {}, httpx.MockTransport(lambda _: httpx.Response(403)), sleep)
    assert len(waits) == 1


async def test_admin_security_setup_pause_and_cron(client, admin_client, monkeypatch):
    monkeypatch.setattr(settings(), "cron_secret", "s" * 40)
    assert (await client.post("/api/v1/internal/cron/results")).status_code == 401
    result = await admin_client.get("/api/v1/admin/market")
    assert result.status_code == 200
    assert "s" * 40 not in result.text
    assert (
        await admin_client.post("/api/v1/admin/market/results/pause", json={"paused": True})
    ).status_code == 200
    admin_client.headers.pop("x-csrf-token")
    assert (await admin_client.post("/api/v1/admin/market/results/run", json={})).status_code == 403


def test_xbrl_rejects_entities_and_ytd():
    with pytest.raises(FeedError, match="UNSAFE_XBRL"):
        parse_instance('<!DOCTYPE x [<!ENTITY a "bad">]><x/>', "c", {}, "STANDALONE")
    with pytest.raises(ValueError, match="discrete quarters"):
        Financial.model_validate(
            observation(
                financial_year=2026,
                quarter=2,
                period_type="QUARTERLY",
                statement_type="STANDALONE",
                period_start="2025-04-01",
                period_end="2025-09-30",
                filing_id="ytd",
            )
        )


async def test_provider_failure_preserves_last_good(db, monkeypatch):
    _, ipo = await tracked(db)
    configured(monkeypatch, "gmp")
    await ingest_record(
        db,
        "gmp",
        Premium.model_validate(observation(value="12")),
        "fixture-feed",
        "UNOFFICIAL",
        None,
    )
    await db.commit()

    async def broken(*args):
        raise FeedError("UPSTREAM_UNAVAILABLE")

    run = await create_run(db, "ipo-live", "manual")
    await run_job(db, run, broken)
    assert run.status == "FAILED"
    assert await db.scalar(select(m.GMP.value).where(m.GMP.ipo_id == ipo.id)) == 12


async def test_discovery_update_listing_and_conflict(db, monkeypatch):
    from apps.worker.market import reconcile_lifecycle
    from packages.providers.market import Issue

    data = Issue.model_validate(
        observation(
            nse_symbol="NEWCO",
            official_status="UPCOMING",
            issue={
                "slug": "new-company",
                "name": "New company",
                "sector": "Services",
                "status": "UPCOMING",
                "open_date": "2026-07-10",
                "close_date": "2026-07-12",
                "listing_date": "2026-07-16",
                "price_high": "100",
                "lot_size": 100,
                "source_url": "https://exchange.example/issue",
            },
        )
    )
    await ingest_record(db, "ipos", data, "NSE", "NSE", None)
    await db.flush()
    await reconcile_lifecycle(db, date(2026, 7, 16))
    company = await db.scalar(select(m.Company).where(m.Company.slug == "new-company"))
    ipo = await db.scalar(select(m.IPO).where(m.IPO.company_id == company.id))
    assert ipo.status == "LISTED" and ipo.lifecycle == "LISTING_TODAY"
    assert company.isin == "INE000A01010"
    changed = data.model_copy(
        update={
            "source_timestamp": datetime(2026, 7, 21, tzinfo=UTC),
            "issue": data.issue.model_copy(update={"listing_price": Decimal("125")}),
        }
    )
    await ingest_record(db, "ipos", changed, "NSE", "NSE", None)
    assert ipo.listing_price == 125
    conflicting = changed.model_copy(
        update={"issue": changed.issue.model_copy(update={"price_high": Decimal("200")})}
    )
    with pytest.raises(FeedError, match="SOURCE_CONFLICT"):
        await ingest_record(db, "ipos", conflicting, "BSE", "BSE", None)


def test_xbrl_context_currency_and_scaling():
    xml = """<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:t="urn:reviewed-taxonomy"><context id="quarter"><entity><identifier scheme="isin">INE000A01010</identifier></entity><period><startDate>2026-04-01</startDate><endDate>2026-06-30</endDate></period></context><unit id="rupees"><measure>iso4217:INR</measure></unit><t:Revenue contextRef="quarter" unitRef="rupees">1200000000</t:Revenue></xbrl>"""
    parsed = parse_instance(
        xml, "quarter", {"revenue": "{urn:reviewed-taxonomy}Revenue"}, "STANDALONE"
    )
    assert parsed["metrics"]["revenue"] == 120
    with pytest.raises(FeedError, match="CURRENCY"):
        parse_instance(
            xml.replace("iso4217:INR", "iso4217:USD"),
            "quarter",
            {"revenue": "{urn:reviewed-taxonomy}Revenue"},
            "STANDALONE",
        )


def test_trading_day_and_event_freshness():
    from zoneinfo import ZoneInfo

    from packages.shared.market_freshness import freshness

    at = datetime(2026, 7, 19, 20, tzinfo=ZoneInfo("Asia/Kolkata"))  # Sunday
    friday = at - timedelta(days=2)
    assert freshness("prices", friday, at) == "FRESH"
    assert freshness("gmp", friday, at, active=False) == "NOT_EXPECTED"
    assert freshness("results", at, at) == "FRESH"  # scan health, not age of last filing


async def test_cron_dispatch_and_backfill_bounds(admin_client, db, monkeypatch):
    from apps.worker.tasks import market_job

    queued = []
    monkeypatch.setattr(market_job, "delay", queued.append)
    monkeypatch.setattr(settings(), "cron_secret", "k" * 40)
    monkeypatch.setattr(settings(), "market_scheduler_enabled", True)
    monkeypatch.setattr(settings(), "market_scheduler_driver", "vercel")
    response = await admin_client.post(
        "/api/v1/internal/cron/results", headers={"Authorization": "Bearer " + "k" * 40}
    )
    assert response.status_code == 202 and response.json()["id"] in queued
    assert (
        await admin_client.post("/api/v1/admin/market/backfill/run", json={})
    ).status_code == 422
    assert (await admin_client.post("/api/v1/admin/market/unknown/run", json={})).status_code == 404
    company, _ = await tracked(db, "LISTED")
    params = {
        "company_id": company.id,
        "from_date": "2020-04-01",
        "to_date": "2026-03-31",
        "confirm_backfill": True,
    }
    assert (
        await admin_client.post("/api/v1/admin/market/backfill/run", json=params)
    ).status_code == 422
    params["from_date"] = "2025-04-01"
    accepted = await admin_client.post("/api/v1/admin/market/backfill/run", json=params)
    assert accepted.status_code == 202 and accepted.json()["id"] in queued


async def test_malformed_envelope_retained(db, monkeypatch):
    configured(monkeypatch, "ipos")

    async def malformed(*args):
        raise FeedError("INVALID_FEED_SCHEMA", raw='{"unexpected":[]}')

    run = await create_run(db, "ipo-master", "manual")
    await run_job(db, run, malformed)
    assert run.status == "FAILED"
    assert await db.scalar(select(m.RawPayload.payload_text)) == '{"unexpected":[]}'

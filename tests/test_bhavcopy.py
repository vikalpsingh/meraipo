"""Synthetic UDiFF fixtures; live-source verification is documented separately."""

import io
import json
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import journey
from apps.worker.bhavcopy import cleanup, preview, process_source, sync
from apps.worker.market import acquire, create_run
from packages.database import models as m
from packages.providers import bhavcopy as feed
from packages.providers.market import FeedError
from packages.shared.config import settings
from tests.test_market_integration import tracked

DAY = date(2026, 7, 20)
HEADER = "TradDt,Src,Sgmt,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol,FinInstrmTp,SsnId\n"
ROW = "2026-07-20,NSE,CM,123,INE000A01010,TRACKED,EQ,120,140,110,125,129,118,1000,STK,F1\n"
CSV = (HEADER + ROW).encode()


def test_supplied_bse_url_builder():
    assert (
        feed.build_bse_url(date(2026, 10, 1))
        == "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20261001_F_0000.CSV"
    )


@pytest.mark.parametrize(
    "exchange,day,filename,close",
    [
        ("NSE", date(2026, 10, 1), "nse-udiff-20261001-sample.csv", "207.26"),
        ("BSE", date(2026, 9, 29), "bse-udiff-20260929-sample.csv", "766.35"),
    ],
)
async def test_real_exchange_sample_http_to_database_to_tracker(
    db, monkeypatch, tmp_path, exchange, day, filename, close
):
    from apps.worker.exchange_pipeline import run_pipeline

    config(monkeypatch, tmp_path, public_display_allowed=True)
    original = (Path(__file__).parent / "fixtures" / filename).read_bytes()
    parsed, errors, total = feed.parse(original, exchange, day)
    assert total == 1 and not errors and parsed[0]["close"] == Decimal(close)
    company, ipo = await tracked(db, "LISTED")
    ipo.issue_price = Decimal("80")  # Upper band remains 100; returns must use that.
    db.add(m.IPODate(ipo_id=ipo.id, listing_date=day))
    company.isin = parsed[0]["isin"]
    await db.commit()
    responses = [
        original,
        original,
        original.replace(close.encode(), str(Decimal(close) + Decimal(".01")).encode()),
    ]

    async def download(url):
        return await feed.download(
            url,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, content=responses[0], headers={"Content-Type": "text/csv"}
                )
            ),
        )

    for expected in ("inserted", "unchanged", "updated"):
        run = await create_run(
            db, "sync-prices", "manual", {"exchange": exchange, "trade_date": day.isoformat()}
        )
        await run_pipeline(db, run, download)
        assert run.status == "SUCCESS", run.counters
        assert run.counters[expected] == 1
        result = await journey(db, company.slug)
        assert result["price_date"] == str(day) and result["closing_exchange"] == exchange
        assert result["cmp"] == float(
            Decimal(close) + (Decimal(".01") if expected == "updated" else 0)
        )
        assert len(result["prices"]) == 1 and result["prices"][0]["exchange"] == exchange
        assert result["listing_price"] == result["cmp"] == float(company.listing_price)
        assert company.listing_price_date == day
        assert company.listing_price_exchange == exchange
        assert result["listing_gain"] == result["return_ipo"] == round(result["cmp"] - 100, 2)
        responses.pop(0)
    assert await db.scalar(select(func.count()).select_from(m.DailyCloseRevision)) == 1


async def test_listing_close_backfill_runtime_returns_and_date_correction(
    db, monkeypatch, tmp_path
):
    from apps.worker.bhavcopy import refresh_listing_prices

    config(monkeypatch, tmp_path, public_display_allowed=True)
    company, ipo = await tracked(db, "LISTED")
    dates = m.IPODate(ipo_id=ipo.id, listing_date=DAY)
    db.add(dates)
    ipo.issue_price = 80
    await db.commit()

    async def load(day, close):
        content = (
            CSV.replace(b"2026-07-20", str(day).encode())
            .replace(b",125,129,", f",{close},129,".encode())
            .replace(b",140,110,", b",140,80,")
        )

        async def download(url):
            return content

        run = await create_run(db, "sync-prices", "manual")
        await process_source(db, run, "NSE", day, download=download)
        await db.commit()

    # A newer CMP must never become a guessed listing price.
    await load(DAY + timedelta(days=1), 130)
    assert company.listing_price is None
    result = await journey(db, company.slug)
    assert result["return_ipo"] == 30 and result["listing_gain"] is None
    # Backfilling the exact listing date must leave the newer CMP intact.
    await load(DAY, 125)
    result = await journey(db, company.slug)
    assert result["cmp"] == 130 and result["listing_price"] == 125
    assert result["listing_gain"] == 25 and result["return_listing"] == 4
    await load(DAY + timedelta(days=2), 90)
    result = await journey(db, company.slug)
    assert result["listing_price"] == 125 and result["return_ipo"] == -10
    # Values are derived when read, not persisted percentages.
    ipo.price_high = 0
    await db.commit()
    result = await journey(db, company.slug)
    assert result["return_ipo"] is None and result["listing_gain"] is None
    ipo.price_high = None
    await db.commit()
    assert (await journey(db, company.slug))["return_ipo"] is None
    config(monkeypatch, tmp_path, public_display_allowed=False)
    result = await journey(db, company.slug)
    assert result["listing_price"] is None and result["cmp"] is None
    # If the source corrects the listing date, clear the old baseline until matched.
    dates.listing_date = DAY - timedelta(days=1)
    await refresh_listing_prices(db)
    assert company.listing_price is None and company.listing_price_date is None


def config(monkeypatch, tmp_path, **overrides):
    sources = {
        exchange: dict(
            enabled=True,
            url_template=f"https://www.{exchange.lower()}india.com/{{yyyymmdd}}.zip",
            verified_on="2026-07-20",
            calendar_year=2026,
            calendar_source="official-test-calendar",
            **overrides,
        )
        for exchange in ("NSE", "BSE")
    }
    monkeypatch.setattr(settings(), "bhavcopy_sources_json", json.dumps(sources))
    monkeypatch.setattr(settings(), "bhavcopy_storage_path", str(tmp_path / "originals"))


def test_parser_close_date_exchange_and_duplicates():
    rows, errors, count = feed.parse(CSV, "NSE", DAY)
    assert count == 1 and not errors and rows[0]["close"] == Decimal("125")
    assert rows[0]["close"] != Decimal("129")
    rows, _, _ = feed.parse(CSV.replace(b"NSE", b"BSE"), "BSE", DAY)
    assert rows[0]["security_id"] == "123"
    for content, exchange, day, code in [
        (CSV, "BSE", DAY, "WRONG_EXCHANGE"),
        (CSV, "NSE", DAY + timedelta(days=1), "WRONG_TRADE_DATE"),
        (b"<html>blocked</html>", "NSE", DAY, "INVALID_BHAVCOPY_CONTENT"),
    ]:
        with pytest.raises(FeedError, match=code):
            feed.parse(content, exchange, day)
    rows, errors, _ = feed.parse((HEADER + ROW + ROW).encode(), "NSE", DAY)
    assert not rows and len(errors) == 2
    assert all(e["code"] == "AMBIGUOUS_SECURITY_ROWS" for e in errors)
    rows, errors, _ = feed.parse(CSV.replace(b",125,129,", b",0,129,"), "NSE", DAY)
    assert not rows and errors[0]["code"] == "MISSING_CLOSE"


def test_zip_safety_and_bom():
    assert feed.parse(b"\xef\xbb\xbf" + CSV, "NSE", DAY)[0]
    for name in ["../daily.csv", "/daily.csv", "C:/daily.csv"]:
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(name, CSV)
        with pytest.raises(FeedError, match="UNSAFE_BHAVCOPY_ARCHIVE"):
            feed.parse(content.getvalue(), "NSE", DAY)
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("daily.csv", CSV)
    assert feed.parse(content.getvalue(), "NSE", DAY)[0]


async def test_bounded_download_blocking_rate_limit_and_html():
    seen, waits = [], []

    async def sleep(delay):
        waits.append(delay)

    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": "30"})

    with pytest.raises(FeedError, match="RATE_LIMITED_RETRY_LATER"):
        await feed.download(
            "https://www.nseindia.com/test", transport=httpx.MockTransport(handler), sleep=sleep
        )
    assert len(seen) == 1 and not waits
    for status, code in [
        (403, "SOURCE_ACCESS_BLOCKED"),
        (404, "NOT_YET_PUBLISHED"),
        (200, "INVALID_BHAVCOPY_CONTENT"),
    ]:
        with pytest.raises(FeedError, match=code):
            await feed.download(
                "https://www.nseindia.com/test",
                transport=httpx.MockTransport(
                    lambda request, status=status: httpx.Response(
                        status, headers={"Content-Type": "text/html"}, text="blocked"
                    )
                ),
            )


async def test_import_corrections_history_exchange_and_retention(db, monkeypatch, tmp_path):
    config(monkeypatch, tmp_path)
    company, _ = await tracked(db, "LISTED")

    async def fetch(url):
        return CSV

    run = await create_run(db, "sync-prices", "manual")
    artifact = await process_source(db, run, "NSE", DAY, download=fetch)
    await db.commit()
    assert artifact.status == "SUCCESS", artifact.error
    assert artifact.counters["inserted"] == 1
    again = await process_source(db, run, "NSE", DAY, download=fetch)
    assert again.checksum == artifact.checksum and again.counters["unchanged"] == 1

    async def corrected(url):
        return CSV.replace(b",125,129,", b",126,129,")

    fixed = await process_source(db, run, "NSE", DAY, download=corrected)
    assert fixed.counters["updated"] == 1
    assert await db.scalar(select(func.count()).select_from(m.DailyCloseRevision)) == 1
    old = DAY - timedelta(days=3)

    async def backfill(url):
        return CSV.replace(b"2026-07-20", old.isoformat().encode())

    await process_source(db, run, "NSE", old, download=backfill)
    snapshot = await db.scalar(
        select(m.PriceSnapshot).where(m.PriceSnapshot.company_id == company.id)
    )
    assert snapshot.price_date == DAY and snapshot.cmp == 126

    async def bse(url):
        return CSV.replace(b"NSE", b"BSE").replace(b",125,129,", b",130,129,")

    await process_source(db, run, "BSE", DAY, download=bse)
    assert snapshot.closing_exchange == "NSE" and snapshot.cmp == 126
    # Disabled public rights must not leak through summary or historical API.
    public = await journey(db, company.slug)
    assert public["cmp"] is None and public["prices"] == []
    config(monkeypatch, tmp_path, public_display_allowed=True)
    public = await journey(db, company.slug)
    assert public["cmp"] == 126 and public["daily_change_pct"] is not None
    assert len(public["prices"]) == 2 and all(p["exchange"] == "NSE" for p in public["prices"])
    artifact.created_at = m.now() - timedelta(days=8)
    await db.commit()
    assert await cleanup(db) == 1
    assert artifact.purged_at and not (tmp_path / "originals" / artifact.path).exists()
    assert (tmp_path / "originals" / again.path).exists()
    assert await db.scalar(select(func.count()).select_from(m.DailyClose)) == 3


async def test_conflicts_missing_values_and_independent_sources(db, monkeypatch, tmp_path):
    config(monkeypatch, tmp_path)
    company, _ = await tracked(db, "LISTED")
    other = m.Company(slug="different", name="Different", isin="INE999A01010")
    db.add(other)
    await db.flush()
    db.add(m.IPO(company_id=other.id, status="LISTED"))
    db.add(m.Identifier(company_id=other.id, exchange="NSE", ticker="TRACKED"))
    await db.commit()
    rows, errors, counts = await preview(db, CSV, "NSE", DAY)
    assert not rows and errors[0]["code"] == "IDENTIFIER_CONFLICT"
    run = await create_run(db, "sync-prices", "manual", {"trade_date": DAY.isoformat()})

    async def fetch(url):
        if "bseindia" in url:
            raise FeedError("SOURCE_ACCESS_BLOCKED")
        return CSV

    counts = dict(fetched=0, written=0, failed=0, unchanged=0, providers=0)
    await sync(db, run, counts, download=fetch)
    assert counts["providers"] == 1 and counts["failed"] == 2
    assert await acquire(db, "first")
    assert not await acquire(db, "second")


def test_calendar_and_ist_schedule():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from packages.shared.market_freshness import next_scheduled

    source = feed.Source(
        calendar_year=2026,
        calendar_source="official",
        holidays=[DAY],
        special_sessions=[date(2026, 7, 19)],
    )
    assert not feed.trading_session(DAY, source)
    assert feed.trading_session(date(2026, 7, 19), source)
    with pytest.raises(FeedError, match="TRADING_CALENDAR_REQUIRED"):
        feed.trading_session(date(2027, 1, 1), source)
    at = datetime(2026, 7, 20, 19, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert next_scheduled("sync-prices", at).startswith("2026-07-20T20:00:00+05:30")


async def test_upload_preview_is_private_and_does_not_import(
    admin_client, client, db, monkeypatch, tmp_path
):
    config(monkeypatch, tmp_path)
    await tracked(db, "LISTED")
    result = await admin_client.post(
        "/api/v1/admin/bhavcopy/preview?exchange=NSE&trade_date=2026-07-20", content=CSV
    )
    assert result.status_code == 200, result.text
    assert result.json()["counters"]["matched"] == 1
    assert await db.scalar(select(func.count()).select_from(m.DailyClose)) == 0
    errors = await admin_client.get("/api/v1/admin/bhavcopy/" + result.json()["id"] + "/errors.csv")
    assert errors.status_code == 200
    result = await admin_client.post(
        "/api/v1/admin/bhavcopy/run", json={"from_date": "2026-01-01", "to_date": "2026-07-20"}
    )
    assert result.status_code == 422
    admin_client.cookies.clear()
    assert (await client.get("/api/v1/admin/bhavcopy")).status_code == 401

"""Focused IPOWEB tests: synthetic inputs only, no live requests."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from apps.worker.market import ingest_record
from packages.database import models as m
from packages.providers.ipo import get_ipo_provider, primary_ipo_provider
from packages.providers.ipoweb import IPOWeb, dates, parse_watch
from packages.providers.market import FeedError, Issue
from packages.shared.config import settings

NOW = datetime(2026, 10, 16, 9, tzinfo=UTC)


def markup(name="Example Industries Limited", window="21-23 Oct", price="258–271"):
    return f"""<h3>Current Mainboard IPO</h3><table>
    <tr><th>Company</th><th>GMP*</th><th>Price Band</th><th>Date</th></tr>
    <tr><td><a href="/example-industries-ipo/">{name}</a> Upcoming</td>
    <td>-</td><td>{price}</td><td>{window}</td></tr></table>""".encode()


def issue(**changes):
    data = parse_watch(markup(), NOW)[1][0][1]
    data.update(changes)
    return Issue.model_validate(data)


def test_web_parse_missing_gmp_prices_dates_and_duplicate_tables():
    _, records, errors = parse_watch(markup() + markup(), NOW)
    assert len(records) == 1 and not errors
    value = records[0][1]
    assert value["issue"]["open_date"] == "2026-10-21"
    assert value["issue"]["price_high"] == "271"
    assert value["issue"]["issue_size"] is None
    assert value["nse_symbol"] is None and value["bse_symbol"] is None
    assert all(kind != "gmp" for kind, _ in records)
    announced = parse_watch(markup(window="To be announced", price="-"), NOW)[1][0][1]
    assert announced["official_status"] == "ANNOUNCED"
    assert announced["issue"]["open_date"] is None
    assert announced["issue"]["price_high"] is None


def test_invalid_or_empty_scrape_is_not_a_valid_snapshot():
    with pytest.raises(FeedError, match="IPOWEB_SCHEMA_CHANGED"):
        parse_watch(b"<html>No data</html>", NOW)
    with pytest.raises(FeedError, match="IPOWEB_SCHEMA_CHANGED"):
        parse_watch(markup(window="32-33 Oct"), NOW)
    assert dates("13 Oct 2026 – 15 Oct 2026", NOW.date())[1].isoformat() == "2026-10-15"


async def test_one_source_failure_does_not_stop_other_sources():
    async def fetch(url):
        raise FeedError("EXCHANGE_HTTP_403")

    async def watch():
        return markup()

    batches = [
        batch
        async for batch in IPOWeb(["nse", "ipowatch"], fetch, watch).batches(time.monotonic() + 60)
    ]
    assert len(batches) == 3
    assert batches[0].errors == [("nse", "EXCHANGE_HTTP_403")]
    assert len(batches[-1].records) == 1 and batches[-1].authority == "UNOFFICIAL"


async def test_repeat_and_provider_switch_reuse_one_company(db, monkeypatch):
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    before = await db.scalar(select(func.count()).select_from(m.Company))
    first = issue()
    assert await ingest_record(db, "ipos", first, "IPOWEB", "UNOFFICIAL", None)
    assert not await ingest_record(db, "ipos", first, "IPOWEB", "UNOFFICIAL", None)
    alert = first.model_copy(deep=True)
    alert.provider_namespace, alert.provider_id = "IPOALERTS", "new-vendor-id"
    alert.nse_symbol = "EXAMPLE"
    alert.source_timestamp = NOW + timedelta(minutes=1)
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    await ingest_record(db, "ipos", alert, "IPOALERTS", "LICENSED", None)
    assert await db.scalar(select(func.count()).select_from(m.Company)) == before + 1
    company_ids = (
        await db.scalars(
            select(m.Identifier.company_id).where(
                m.Identifier.exchange.in_(["IPOWEB", "IPOALERTS"])
            )
        )
    ).all()
    assert len(set(company_ids)) == 1
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    first.source_timestamp = NOW + timedelta(minutes=2)
    await ingest_record(db, "ipos", first, "IPOWEB", "UNOFFICIAL", None)
    assert await db.scalar(select(func.count()).select_from(m.Company)) == before + 1


async def test_ambiguous_same_name_different_dates_does_not_create_duplicate(db, monkeypatch):
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    first = issue()
    await ingest_record(db, "ipos", first, "IPOWEB", "UNOFFICIAL", None)
    other = first.model_copy(deep=True)
    other.provider_id = "different-source-id"
    other.issue.open_date += timedelta(days=1)
    before = await db.scalar(select(func.count()).select_from(m.Company))
    with pytest.raises(FeedError, match="IPOWEB_IDENTITY_REVIEW_REQUIRED"):
        await ingest_record(db, "ipos", other, "IPOWEB", "UNOFFICIAL", None)
    assert await db.scalar(select(func.count()).select_from(m.Company)) == before


async def test_web_cannot_replace_official_price(db, monkeypatch):
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    official = issue(nse_symbol="EXAMPLE")
    await ingest_record(db, "ipos", official, "IPOWEB", "NSE", None)
    web = official.model_copy(deep=True)
    web.source_timestamp += timedelta(minutes=1)
    web.issue.price_high += 1
    with pytest.raises(FeedError, match="SOURCE_CONFLICT"):
        await ingest_record(db, "ipos", web, "IPOWEB", "UNOFFICIAL", None)


def test_provider_configuration_selects_ipoweb(monkeypatch):
    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    monkeypatch.setattr(settings(), "ipoweb_sources", ["nse"])
    assert isinstance(get_ipo_provider(settings()), IPOWeb)
    assert get_ipo_provider(settings()).sources == ["nse"]
    assert primary_ipo_provider(settings()) == "IPOWEB"


async def test_pipeline_populates_public_catalog_and_repeated_run_is_idempotent(db, monkeypatch):
    from apps.api.repository import catalog
    from apps.worker.exchange_pipeline import run_pipeline
    from apps.worker.market import create_run
    from packages.providers import ipo as registry

    async def watch():
        return markup()

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoweb")
    monkeypatch.setattr(
        registry, "get_ipo_provider", lambda config: IPOWeb(["ipowatch"], watch_fetch=watch)
    )
    before = await db.scalar(select(func.count()).select_from(m.Company))
    first = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, first)
    assert first.status == "SUCCESS", first.error
    assert await db.scalar(select(func.count()).select_from(m.Company)) == before + 1
    output = await catalog(db)
    assert "Example Industries Limited" in str(output)
    second = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, second)
    assert second.status == "SUCCESS", second.error
    assert await db.scalar(select(func.count()).select_from(m.Company)) == before + 1


def test_optional_size_lot_and_year_rollover():
    from datetime import date

    content = markup().replace(
        b"<th>Date</th>", b"<th>Lot size</th><th>Issue size (crore)</th><th>Date</th>"
    )
    content = content.replace(
        b"<td>21-23 Oct</td>", b"<td>1,200</td><td>145.5</td><td>21-23 Oct</td>"
    )
    record = parse_watch(content, NOW)[1][0][1]["issue"]
    assert record["lot_size"] == 1200 and record["issue_size"] == "145.5"
    assert dates("2-4 Jan", date(2026, 12, 28))[0] == date(2027, 1, 2)

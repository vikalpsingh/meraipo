"""Synthetic payloads use field bindings from BSE's published IPO component.

These test population contracts, not the availability of BSE's live endpoint.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from apps.api.repository import catalog
from apps.worker.exchange_pipeline import run_pipeline
from apps.worker.market import create_run
from packages.database import models as m
from packages.providers import exchanges as ex
from packages.providers.bse_ipo import BSE_LIST_URL, parse_issues
from packages.providers.market import FeedError
from packages.shared.config import settings

AT = datetime(2026, 9, 20, tzinfo=UTC)


def bse_row(**changes):
    return {
        "IPO_NO": 90001,
        "Scrip_cd": "BSEONLY",
        "Scrip_Name": "BSE Only Fixture Limited",
        "IR_flag": "P",
        "IR_FLAG_FULL": "IPO",
        "eXCHANGE_PLATFORM": "SME",
        "Start_Dt": "2026-09-17T00:00:00",
        "End_Dt": "2026-09-25T00:00:00",
        "Status": "L",
        "Price_Band": "Rs.100 to Rs.110",
        **changes,
    }


def body(rows):
    return json.dumps({"Table": rows}).encode()


def test_bse_listing_schema_dates_filtering_and_row_error_context():
    _, records, errors = parse_issues(
        body(
            [
                bse_row(),
                bse_row(
                    IPO_NO=90002,
                    Scrip_cd="500123",
                    eXCHANGE_PLATFORM="Main Board",
                    Start_Dt="2026-09-22T00:00:00",
                    Status="F",
                ),
                bse_row(IPO_NO=90003, IR_flag="OFS"),
                bse_row(IPO_NO=90004, Price_Band="10 to 20 to 30"),
            ]
        ),
        AT,
    )
    assert len(records) == 2
    assert records[0][1]["bse_symbol"] == "BSEONLY"
    assert records[0][1]["issue"]["board"] == "SME"
    assert records[1][1]["bse_code"] == "500123"
    assert records[1][1]["issue"]["status"] == "UPCOMING"
    assert "90004" in errors[0][0] and "BSE Only Fixture" in errors[0][0]
    assert errors[0][1] == "BSE_INVALID_PRICE_BAND"
    for content in [b"<html>Member login</html>", b"{}", b"[]"]:
        with pytest.raises(FeedError, match="BSE_IPO_SCHEMA_CHANGED"):
            parse_issues(content, AT)


async def test_bse_only_and_existing_mirror_publish_once_in_same_job(db, monkeypatch):
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(m, "now", lambda: AT)
    monkeypatch.setattr("apps.worker.market.india_today", lambda: AT.date())
    snapshot = json.loads(
        (Path(__file__).parent / "fixtures/nse-ipo-snapshot.json").read_text(encoding="utf-8-sig")
    )

    async def download(url):
        if url == BSE_LIST_URL:
            return body(
                [
                    bse_row(),
                    bse_row(
                        IPO_NO=90005,
                        Scrip_cd="AXIOMGAS",
                        Scrip_Name="Axiom Gas Engineering Limited",
                        Start_Dt="2026-09-18T00:00:00",
                        End_Dt="2026-09-22T00:00:00",
                        Price_Band=None,
                    ),
                ]
            )
        return json.dumps(snapshot["catalog" if url == ex.NSE_UPCOMING else "current"]).encode()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.counters
    companies = [c for c in await catalog(db) if not c["is_demo"]]
    assert len(companies) == 8
    added = next(c for c in companies if c["name"] == "BSE Only Fixture Limited")
    assert added["board"] == "SME" and added["price_high"] == 110
    assert added["exchange"] == "BSE"
    assert sum(c["name"] == "Axiom Gas Engineering Limited" for c in companies) == 1
    alias = await db.scalar(
        select(m.Identifier).where(
            m.Identifier.exchange == "BSE_ISSUE", m.Identifier.ticker == "90005"
        )
    )
    assert alias is not None
    retry = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, retry, download)
    assert retry.counters["written"] == 0


async def test_bse_failure_logged_while_nse_still_publishes(db, monkeypatch):
    from tests.test_exchange_pipeline import ipo_body

    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)

    async def download(url):
        if url == BSE_LIST_URL:
            raise FeedError("EXCHANGE_HTTP_301")
        return b"[]" if url == ex.NSE_UPCOMING else ipo_body()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "PARTIAL" and run.counters["written"] == 2
    error = await db.scalar(select(m.JobError).where(m.JobError.run_id == run.id))
    assert error.provider == "BSE" and error.code == "BSE_ACCESS_REDIRECT"
    assert BSE_LIST_URL in error.item and "permitted API access" in error.detail


async def test_unverified_cross_exchange_match_is_rejected_not_duplicated(db, monkeypatch):
    from tests.test_exchange_pipeline import ipo_body

    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)

    async def download(url):
        if url == BSE_LIST_URL:
            return body([bse_row(Scrip_Name="Example Industries", Scrip_cd="OTHERID")])
        return b"[]" if url == ex.NSE_UPCOMING else ipo_body()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "PARTIAL"
    error = await db.scalar(select(m.JobError).where(m.JobError.run_id == run.id))
    assert "90001" in error.item and "Example Industries" in error.item
    assert (
        await db.scalar(
            select(func.count()).select_from(m.Company).where(m.Company.is_demo.is_(False))
        )
        == 1
    )
    assert (
        await db.scalar(select(m.MarketStage.error).where(m.MarketStage.status == "REJECTED"))
        == "BSE_CROSS_EXCHANGE_MAPPING_REQUIRED"
    )

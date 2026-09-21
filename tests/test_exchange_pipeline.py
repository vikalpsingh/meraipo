import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import catalog, journey
from apps.worker.exchange_pipeline import raw_payload, run_pipeline, stage
from apps.worker.market import create_run, ingest_record
from packages.database import models as m
from packages.providers import exchanges as ex
from packages.providers.bse_ipo import BSE_LIST_URL
from packages.providers.market import FeedError, Subscriptions
from packages.shared.config import settings
from packages.shared.market_freshness import next_scheduled
from tests.test_market_integration import observation, tracked


async def test_nse_current_and_catalog_publish_all_seven_issues_without_false_tickers(
    db, monkeypatch
):
    snapshot = json.loads(
        (Path(__file__).parent / "fixtures/nse-ipo-snapshot.json").read_text(encoding="utf-8-sig")
    )
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    at = datetime(2026, 9, 20, 15, tzinfo=UTC)
    monkeypatch.setattr(m, "now", lambda: at)
    monkeypatch.setattr("apps.worker.market.india_today", lambda: at.date())

    async def download(url):
        if url == BSE_LIST_URL:
            return b'{"Table": []}'
        return json.dumps(snapshot["catalog" if url == ex.NSE_UPCOMING else "current"]).encode()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.counters
    rows = [c for c in await catalog(db) if not c["is_demo"]]
    assert len(rows) == 7
    assert sum(c["status"] == "OPEN" for c in rows) == 5
    assert sum(c["status"] == "UPCOMING" for c in rows) == 2
    assert sum(c["board"] == "SME" for c in rows) == 4
    assert sum(c["subscription"] is not None for c in rows) == 5
    pooja = next(c for c in rows if c["slug"] == "nse-poojalogis")
    assert pooja["lot_size"] == 1200 and pooja["price_high"] == 115
    assert (
        await db.scalar(
            select(m.Identifier.id).where(
                m.Identifier.exchange == "NSE", m.Identifier.ticker == "AXIOMGAS"
            )
        )
        is None
    )
    assert await db.scalar(
        select(m.Identifier.id).where(
            m.Identifier.exchange == "BSE_SYMBOL", m.Identifier.ticker == "AXIOMGAS"
        )
    )
    repeat = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, repeat, download)
    assert repeat.counters["written"] == 0
    assert await db.scalar(select(func.count()).select_from(m.SubscriptionDay)) == 5


async def test_error_log_links_error_to_run(admin_client, db):
    run = await create_run(db, "sync-ipos", "manual")
    db.add(
        m.JobError(
            run_id=run.id,
            provider="NSE",
            item=ex.NSE_UPCOMING,
            code="EXCHANGE_HTTP_404",
            detail="Verify the official endpoint.",
        )
    )
    await db.commit()
    result = await admin_client.get("/api/v1/admin/market/errors")
    assert result.status_code == 200
    error = result.json()["items"][0]
    assert error["job_name"] == "sync-ipos" and error["run_id"] == run.id
    assert error["created_at"] and error["code"] == "EXCHANGE_HTTP_404"


async def test_error_log_requires_admin(client):
    assert (await client.get("/api/v1/admin/market/errors")).status_code == 401


AT = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)
DAY = date(2026, 7, 20)
CSV = b"TradDt,ISIN,TckrSymb,FinInstrmId,SctySrs,ClsPric,OpnPric,HghPric,LwPric,PrvsClsgPric,TtlTradgVol,TtlTrfVal\n2026-07-20,INE000A01010,TRACKED,500001,EQ,125,120,130,119,118,1000,125000\n2026-07-20,INE999A01010,OUTSIDE,500002,EQ,50,50,50,50,50,100,5000\n"


def test_bhavcopy_zip_filters_universe_and_checks_date():
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("daily.csv", CSV)
    ids = {"isin": {"INE000A01010"}, "NSE": set(), "BSE": set()}
    raw, records, errors = ex.parse_bhavcopy(zipped.getvalue(), "NSE", DAY, ids, AT)
    assert len(records) == 1 and not errors
    assert records[0][1]["close"] == "125"
    assert "OUTSIDE" in raw  # Unmodified source remains auditable.
    _, wrong, errors = ex.parse_bhavcopy(CSV, "NSE", date(2026, 7, 21), ids, AT)
    assert not wrong and errors == [("0", "WRONG_TRADE_DATE")]
    _, records, errors = ex.parse_bhavcopy(
        CSV.replace(b",125,120,", b",bad,120,"), "NSE", DAY, ids, AT
    )
    assert not records and errors


def test_schema_change_is_not_an_empty_success():
    with pytest.raises(FeedError, match="UDIFF_SCHEMA_CHANGED"):
        ex.parse_bhavcopy(b"<html>Access denied</html>", "BSE", DAY, {}, AT)


async def test_exchange_denial_no_retry_or_redirect():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(403, text="Forbidden")

    with pytest.raises(FeedError, match="EXCHANGE_HTTP_403"):
        await ex.download(ex.NSE_IPO, transport=httpx.MockTransport(handler))
    assert len(seen) == 1
    with pytest.raises(FeedError, match="UNAPPROVED_EXCHANGE_URL"):
        await ex.download("http://127.0.0.1/secrets")


def ipo_body():
    return json.dumps(
        [
            {
                "companyName": "Example Industries",
                "symbol": "EXAMPLE",
                "issueStartDate": "20-Jul-2026",
                "issueEndDate": "22-Jul-2026",
                "issuePrice": "Rs.100 to Rs.110",
                "series": "EQ",
                "noOfTime": "2.5",
                "noOfsharesBid": "2500",
                "noOfSharesOffered": "1000",
            }
        ]
    ).encode()


async def test_collection_does_not_publish_and_repeat_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)

    async def download(url):
        if url == BSE_LIST_URL:
            return b'{"Table": []}'
        return b"[]" if url == ex.NSE_UPCOMING else ipo_body()

    run = await create_run(db, "collect-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.error
    assert await db.scalar(select(func.count()).select_from(m.MarketStage)) == 2
    assert not await db.scalar(select(m.Company.id).where(m.Company.slug == "nse-example"))
    repeat = await create_run(db, "collect-ipos", "manual")
    await run_pipeline(db, repeat, download)
    assert await db.scalar(select(func.count()).select_from(m.MarketStage)) == 2
    publish = await create_run(db, "publish-ipos", "manual")
    await run_pipeline(db, publish)
    assert publish.status == "SUCCESS", publish.error
    item = next(c for c in await catalog(db) if c["slug"] == "nse-example")
    assert item["subscription"]["multiple"] == 2.5
    details = await journey(db, "nse-example")
    assert details["subscription_history"][0]["subscription_pct"] == 250
    repeat = await create_run(db, "publish-ipos", "manual")
    await run_pipeline(db, repeat)
    assert repeat.status == "SKIPPED" and repeat.error == "NO_PENDING_RECORDS"


async def test_failed_download_retains_published_data(db, monkeypatch):
    company, ipo = await tracked(db)
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)

    async def failure(url):
        raise FeedError("EXCHANGE_HTTP_403")

    run = await create_run(db, "collect-ipos", "manual")
    await run_pipeline(db, run, failure)
    assert run.status == "FAILED"
    assert (await db.get(m.IPO, ipo.id)).issue_price == 100
    assert (
        await db.scalar(
            select(func.count()).select_from(m.JobError).where(m.JobError.run_id == run.id)
        )
        == 3
    )


async def test_exchange_history_preserves_both_and_nse_wins(db):
    company, _ = await tracked(db, "LISTED")
    for exchange, close in (("BSE", "126"), ("NSE", "125")):
        payload = await raw_payload(
            db, exchange, "prices", ex.bhavcopy_url(exchange, DAY), "source"
        )
        await stage(
            db,
            "prices",
            observation(price_date=DAY.isoformat(), close=close),
            exchange,
            exchange,
            payload.id,
        )
    await db.commit()
    run = await create_run(db, "publish-prices", "manual")
    await run_pipeline(db, run)
    assert run.status == "SUCCESS"
    assert await db.scalar(select(m.Price.close).where(m.Price.company_id == company.id)) == 125
    assert await db.scalar(select(func.count()).select_from(m.ExchangePrice)) == 2
    assert (
        await db.scalar(select(m.PriceSnapshot.cmp).where(m.PriceSnapshot.company_id == company.id))
        == 125
    )


async def test_bse_fallback_then_nse_replaces_canonical(db):
    company, _ = await tracked(db, "LISTED")
    for exchange, close in (("BSE", "126"), ("NSE", "125")):
        payload = await raw_payload(
            db, exchange, "prices", ex.bhavcopy_url(exchange, DAY), "source"
        )
        await stage(
            db,
            "prices",
            observation(price_date=DAY.isoformat(), close=close),
            exchange,
            exchange,
            payload.id,
        )
        run = await create_run(db, "publish-prices", "manual")
        await run_pipeline(db, run)
        assert run.status == "SUCCESS"
        assert await db.scalar(
            select(m.Price.close).where(m.Price.company_id == company.id)
        ) == Decimal(close)


async def test_daily_subscription_join_updates_and_retains_dates(db):
    company, _ = await tracked(db)
    for day, multiple in ((20, "2.5"), (20, "3"), (21, "3")):
        data = Subscriptions.model_validate(
            observation(
                source_timestamp=f"2026-07-{day}T12:00:00Z",
                categories={"retail": {"multiple": multiple}},
            )
        )
        await ingest_record(db, "subscriptions", data, "NSE", "NSE", None)
    await db.commit()
    history = (await journey(db, company.slug))["subscription_history"]
    assert len(history) == 2
    assert [r["subscription_pct"] for r in history] == [300, 300]


def test_subscription_ratio_and_friday_schedule():
    data = Subscriptions.model_validate(
        observation(categories={"retail": {"bid_shares": 250, "offered_shares": 100}})
    )
    assert data.categories["retail"].multiple == Decimal("2.5")
    with pytest.raises(ValueError, match="disagrees"):
        Subscriptions.model_validate(
            observation(
                categories={"retail": {"bid_shares": 250, "offered_shares": 100, "multiple": 10}}
            )
        )
    at = datetime(2026, 9, 18, 21, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert next_scheduled("collect-results", at).startswith("2026-09-25T21:00")
    assert next_scheduled("publish-results", at).startswith("2026-09-18T21:30")


def test_financial_xml_context_units_and_unsafe_xml():
    xml = '<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:t="urn:reviewed"><context id="quarter"><entity><identifier scheme="isin">INE000A01010</identifier></entity><period><startDate>2026-04-01</startDate><endDate>2026-06-30</endDate></period></context><unit id="rupees"><measure>iso4217:INR</measure></unit><t:Revenue contextRef="quarter" unitRef="rupees">1200000000</t:Revenue></xbrl>'
    result = ex.financial_records(
        xml, observation(filing_id="filing-1"), {"revenue": "{urn:reviewed}Revenue"}
    )
    assert result[0]["revenue"] == "120"
    assert result[0]["quarter"] == 1
    assert result[0]["statement_type"] == "STANDALONE"
    with pytest.raises(FeedError, match="UNSAFE_XBRL"):
        ex.financial_records("<!DOCTYPE bad>" + xml, {}, {"revenue": "x"})
    with pytest.raises(FeedError, match="XBRL_TAXONOMY_NOT_CONFIGURED"):
        ex.financial_records(xml, {}, {})


async def test_publish_bad_mapping_isolated_and_retryable(db):
    payload = await raw_payload(db, "NSE", "subscriptions", ex.NSE_IPO, "source")
    await stage(
        db,
        "subscriptions",
        observation(categories={"total": {"multiple": "2"}}),
        "NSE",
        "NSE",
        payload.id,
    )
    run = await create_run(db, "publish-ipos", "manual")
    await run_pipeline(db, run)
    assert run.status == "PARTIAL"
    assert await db.scalar(select(m.MarketStage.status)) == "REJECTED"
    await tracked(db)
    retry = await create_run(db, "publish-ipos", "manual", {"retry_rejected": True})
    await run_pipeline(db, retry)
    assert retry.status == "SUCCESS"
    assert await db.scalar(select(m.MarketStage.status)) == "PUBLISHED"


@pytest.mark.parametrize("single_job", [False, True])
async def test_native_financial_discovery_stages_then_publishes(db, monkeypatch, single_job):
    await tracked(db, "LISTED")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(
        settings(),
        "exchange_sources_json",
        json.dumps(
            [
                {
                    "name": "NSE-reviewed-results",
                    "exchange": "NSE",
                    "kind": "results",
                    "url": "https://www.nseindia.com/api/integrated-filing-results",
                    "records_path": "data",
                    "fields": {
                        "isin": "isin",
                        "xbrl_url": "xbrl",
                        "source_timestamp": "broadcast",
                        "filing_id": "id",
                    },
                    "concepts": {"revenue": "{urn:reviewed}Revenue"},
                }
            ]
        ),
    )
    xml = '<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:t="urn:reviewed"><context id="quarter"><entity><identifier scheme="isin">INE000A01010</identifier></entity><period><startDate>2026-04-01</startDate><endDate>2026-06-30</endDate></period></context><unit id="rupees"><measure>iso4217:INR</measure></unit><t:Revenue contextRef="quarter" unitRef="rupees">1200000000</t:Revenue></xbrl>'
    requests = []

    async def download(url):
        requests.append(url)
        if url.endswith(".xml"):
            return xml.encode()
        return json.dumps(
            {
                "data": [
                    {
                        "isin": "INE000A01010",
                        "xbrl": "https://nsearchives.nseindia.com/corporate/example.xml",
                        "broadcast": "20-Jul-2026 16:00:00",
                        "id": "q1-fixture",
                    }
                ]
            }
        ).encode()

    run = await create_run(db, "sync-results" if single_job else "collect-results", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS"
    if not single_job:
        assert not (await journey(db, "real-fixture"))["quarters"]
        run = await create_run(db, "publish-results", "manual")
        await run_pipeline(db, run)
        assert run.status == "SUCCESS"
    else:
        assert run.counters["staged"] == 1 and run.counters["written"] == 1
    assert (await journey(db, "real-fixture"))["quarters"][0]["revenue"] == 120
    run = await create_run(db, "collect-results", "manual")
    await run_pipeline(db, run, download)
    assert len([r for r in requests if r.endswith(".xml")]) == 1


async def test_authenticated_cron_prevents_two_scheduler_owners(admin_client, monkeypatch):
    monkeypatch.setattr(settings(), "cron_secret", "x" * 40)
    monkeypatch.setattr(settings(), "market_scheduler_enabled", True)
    monkeypatch.setattr(settings(), "market_scheduler_driver", "celery")
    response = await admin_client.post(
        "/api/v1/internal/cron/collect-ipos", headers={"Authorization": "Bearer " + "x" * 40}
    )
    assert response.status_code == 409


async def test_official_close_confirms_listing_without_inventing_listing_price(db):
    company, ipo = await tracked(db, "CLOSED")
    db.add(m.IPODate(ipo_id=ipo.id, close_date=date(2026, 7, 17)))
    payload = await raw_payload(db, "NSE", "prices", ex.bhavcopy_url("NSE", DAY), "source")
    await stage(
        db, "prices", observation(price_date=DAY.isoformat(), close="125"), "NSE", "NSE", payload.id
    )
    run = await create_run(db, "publish-prices", "manual")
    await run_pipeline(db, run)
    assert run.status == "SUCCESS"
    assert ipo.status == "LISTED"
    assert ipo.listing_price is None
    assert (await journey(db, company.slug))["listing_date"] is None


async def test_same_job_stages_then_populates_public_master(db, monkeypatch):
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)

    async def download(url):
        if url == BSE_LIST_URL:
            return b'{"Table": []}'
        return b"[]" if url == ex.NSE_UPCOMING else ipo_body()

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS"
    assert run.counters["staged"] == 2 and run.counters["written"] == 2
    assert (await journey(db, "nse-example"))["subscription"]["multiple"] == 2.5
    assert await db.scalar(select(m.MarketStage.status).limit(1)) == "PUBLISHED"
    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, download)
    assert run.counters["written"] == 0


async def test_single_price_job_collects_both_exchanges_and_populates_ui(db, monkeypatch):
    await tracked(db, "LISTED")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(settings(), "trading_calendar_year", DAY.year)
    monkeypatch.setattr("apps.worker.exchange_pipeline.india_today", lambda: DAY)
    seen = []

    async def download(url):
        seen.append(url)
        return CSV

    run = await create_run(db, "sync-prices", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.error
    assert len(seen) == 2
    assert (await journey(db, "real-fixture"))["cmp"] == 125
    assert await db.scalar(select(func.count()).select_from(m.ExchangePrice)) == 2


def test_bse_cumulative_categories_and_schema_guard():
    from packages.providers.bse_ipo import BseIpoProvider, BseIssue

    html = b"<h1>Cumulative Demand Schedule</h1><table><tr><th>Category</th><th>Shares offered</th><th>Shares bid</th><th>Subscription X</th></tr><tr><td>QIB</td><td>1,000</td><td>5,000</td><td>5.00</td></tr><tr><td>Retail</td><td>2000</td><td>6000</td><td>3.00</td></tr></table>"
    issue = BseIssue(issue_id="7154", isin="INE000A01010")
    _, records, errors = BseIpoProvider.parse(html, issue, AT)
    assert not errors
    assert records[0][1]["categories"]["retail"]["multiple"] == "3.0000"
    with pytest.raises(FeedError, match="BSE_CUMULATIVE_PAGE_REQUIRED"):
        BseIpoProvider.parse(b"Access denied", issue, AT)


async def test_nse_total_and_bse_categories_are_merged_without_adding_totals(db):
    company, _ = await tracked(db)
    for provider, categories in (
        ("NSE", {"total": {"multiple": "4"}}),
        ("BSE", {"retail": {"multiple": "3"}, "total": {"multiple": "4.2"}}),
    ):
        data = Subscriptions.model_validate(observation(categories=categories))
        await ingest_record(db, "subscriptions", data, provider, provider, None)
    result = await journey(db, company.slug)
    assert result["subscription"]["multiple"] == 4
    assert result["subscription"]["categories"]["retail"]["multiple"] == "3"
    assert result["subscription"]["source_disagreement"] is True
    assert result["subscription"]["categories"]["retail"]["source_provider"] == "BSE"


async def test_unchanged_gmp_still_has_a_fresh_daily_observation(db):
    company, _ = await tracked(db)
    payload = await raw_payload(db, "unofficial", "gmp", "https://gmp.example/quote", "source")
    for day in (20, 21):
        assert await stage(
            db,
            "gmp",
            observation(value="12", source_timestamp=f"2026-07-{day}T17:30:00Z"),
            "unofficial",
            "UNOFFICIAL",
            payload.id,
        )
    run = await create_run(db, "publish-ipos", "manual")
    await run_pipeline(db, run)
    result = await journey(db, company.slug)
    assert result["gmp"] == 12
    assert result["gmp_timestamp"].startswith("2026-07-21")

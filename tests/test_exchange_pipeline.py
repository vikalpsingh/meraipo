import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import catalog, journey
from apps.worker.exchange_pipeline import raw_payload, run_pipeline, stage
from apps.worker.market import create_run, ingest_record
from packages.database import models as m
from packages.providers import exchanges as ex
from packages.providers.market import FeedError, Subscriptions
from packages.shared.config import settings
from packages.shared.market_freshness import next_scheduled
from tests.test_market_integration import observation, tracked

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
        == 2
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


async def test_native_financial_discovery_stages_then_publishes(db, monkeypatch):
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

    run = await create_run(db, "collect-results", "manual")
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS"
    assert not (await journey(db, "real-fixture"))["quarters"]
    run = await create_run(db, "publish-results", "manual")
    await run_pipeline(db, run)
    assert run.status == "SUCCESS"
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
    await stage(db, "prices", observation(price_date=DAY.isoformat(), close="125"), "NSE", "NSE", payload.id)
    run = await create_run(db, "publish-prices", "manual")
    await run_pipeline(db, run)
    assert run.status == "SUCCESS"
    assert ipo.status == "LISTED"
    assert ipo.listing_price is None
    assert (await journey(db, company.slug))["listing_date"] is None

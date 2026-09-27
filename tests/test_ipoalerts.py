"""Provider contract and full staging/master/UI population tests use synthetic data."""

import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from apps.api.repository import catalog
from apps.worker.exchange_pipeline import run_pipeline
from apps.worker.market import create_run
from packages.database import models as m
from packages.providers.ipoalerts import IPOAlerts, normalize, normalize_gmp
from packages.providers.market import FeedError
from packages.shared.config import settings


def row(**changes):
    return dict(
        id="fixture-123",
        source="nse",
        status="open",
        slug="provider-fixture",
        name="Provider Fixture Limited",
        symbol="FIXTURE",
        type="EQ",
        startDate="2026-09-17",
        endDate="2026-09-25",
        listingDate="2026-09-29",
        priceRange="94-99",
        minQty=150,
        minAmount=14850,
        issueSize="142cr",
        about="Provider business description.",
        strengths=["Strength one"],
        risks=["Risk one"],
        schedule=[
            {"event": "Allotment finalization", "date": "2026-09-26"},
            {"event": "UPI mandate deadline", "date": "2026-09-25"},
        ],
        **changes,
    )


def response(rows, page=1, pages=1, count=None, **extra):
    return {
        "meta": dict(
            count=len(rows) if count is None else count,
            countOnPage=len(rows),
            totalPages=pages,
            page=page,
            limit=100,
            **extra,
        ),
        "ipos": rows,
    }


async def no_sleep(delay):
    pass


def test_gmp_mapping_uses_aggregate_and_traceable_source_fallback():
    aggregate = row(
        gmp={
            "aggregations": {"mean": 18},
            "lastUpdatedAt": "2026-09-27T08:15:00Z",
            "sources": [{"name": "source-a", "gmpPrice": 17}],
        }
    )
    assert normalize_gmp(aggregate)["value"] == "18"
    fallback = row(
        gmp={
            "lastUpdatedAt": "2026-09-27T08:15:00Z",
            "sources": [
                {"name": "source-a", "gmpPrice": 16},
                {"name": "source-b", "gmpPrice": 20},
            ],
        }
    )
    assert normalize_gmp(fallback)["value"] == "18"


def test_gmp_mapping_keeps_unpublished_quote_missing_and_requires_timestamp():
    assert normalize_gmp(row(gmp={"sources": []})) is None
    with pytest.raises(ValueError, match="timestamp"):
        normalize_gmp(row(gmp={"sources": [{"name": "source-a", "gmpPrice": 18}]}))


def transport_for(items):
    def handle(request):
        assert request.headers["x-api-key"] == "test-secret"
        assert "test-secret" not in str(request.url)
        return httpx.Response(
            200, json=response(items if request.url.params["status"] == "open" else [])
        )

    return httpx.MockTransport(handle)


def test_mapping_all_fields_missing_announced_type_and_bse_identity():
    now = datetime.now(UTC)
    item = normalize(row(), now)
    assert item["issue"]["price_high"] == "99" and item["issue"]["issue_size"] == "142"
    assert item["issue"]["lot_size"] == 150
    assert item["provider_details"]["minimum_amount"] == "14850"
    assert item["allotment_date"] == "2026-09-26"
    assert item["provider_namespace"] == "IPOALERTS"
    announced = row()
    announced.update(
        status="announced",
        type=None,
        startDate=None,
        endDate=None,
        listingDate=None,
        priceRange=None,
        minQty=None,
        minAmount=None,
        issueSize="–",
        schedule=[],
    )
    assert normalize(announced, now)["issue"]["board"] == "Unknown"
    assert normalize(announced, now)["official_status"] == "ANNOUNCED"
    bse = row()
    bse.update(
        source="bse",
        type="SME",
        bseInfoUrl="https://www.bseindia.com/markets/publicIssues/DisplayIPO?IPONo=7983&id=4834",
    )
    mapped = normalize(bse, now)
    assert mapped["bse_symbol"] == "FIXTURE" and mapped["bse_issue_id"] == "7983"
    assert mapped["nse_symbol"] is None and mapped["bse_code"] is None
    assert len(mapped["provider_details"]["schedule"]) == 2


async def test_pagination_collects_every_status_and_rejects_truncated_preview():
    calls = []

    def handler(request):
        status = request.url.params["status"]
        page = int(request.url.params["page"])
        calls.append((status, page))
        items = []
        if status == "open":
            item = row()
            item["id"] = f"fixture-{page}"
            items = [item]
        return httpx.Response(
            200,
            json=response(items, page, 2 if status == "open" else 1, 2 if status == "open" else 0),
        )

    batches = [
        b
        async for b in IPOAlerts(
            "test-secret", transport=httpx.MockTransport(handler), sleep=no_sleep
        ).batches(time.monotonic() + 60)
    ]
    assert sum(len(b.records) for b in batches) == 2
    assert ("open", 2) in calls and ("announced", 1) in calls
    preview = httpx.MockTransport(
        lambda r: httpx.Response(200, json=response([row()], info="API key required"))
    )
    with pytest.raises(FeedError, match="IPOALERTS_INCOMPLETE_ACCESS"):
        _ = [
            b
            async for b in IPOAlerts("test-secret", transport=preview, sleep=no_sleep).batches(
                time.monotonic() + 60
            )
        ]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_FAILED"),
        (403, "AUTH_FAILED"),
        (429, "RATE_LIMITED"),
        (302, "HTTP_ERROR"),
        (500, "UNAVAILABLE"),
    ],
)
async def test_safe_failures(status, code):
    with pytest.raises(FeedError, match="IPOALERTS_" + code) as error:
        _ = [
            b
            async for b in IPOAlerts(
                "test-secret",
                transport=httpx.MockTransport(lambda r: httpx.Response(status)),
                sleep=no_sleep,
            ).batches(time.monotonic() + 60)
        ]
    assert "test-secret" not in str(error.value)


async def test_page_failure_does_not_publish_partial_status():
    def handler(request):
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=response([row()], pages=2, count=2))
        return httpx.Response(401)

    batches = []
    with pytest.raises(FeedError):
        async for batch in IPOAlerts(
            "test-secret", transport=httpx.MockTransport(handler), sleep=no_sleep
        ).batches(time.monotonic() + 60):
            batches.append(batch)
    assert batches == []


async def test_population_repetition_provider_switch_and_public_projection(db, monkeypatch):
    from packages.providers import ipo as registry

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    monkeypatch.setattr(settings(), "ipoalerts_api_key", SecretStr("test-secret"))
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    first = row()
    bse = row()
    bse.update(
        id="fixture-bse",
        slug="bse-fixture",
        name="BSE Fixture Limited",
        symbol="BSEFIX",
        source="bse",
        type="SME",
    )
    announced = row()
    announced.update(
        id="fixture-announced",
        slug="announced-fixture",
        name="Announced Fixture",
        symbol="ANNOUNCED",
        status="announced",
        type=None,
        startDate=None,
        endDate=None,
        listingDate=None,
        priceRange=None,
        minQty=None,
        minAmount=None,
        issueSize="–",
        schedule=[],
    )

    def handler(request):
        status = request.url.params["status"]
        return httpx.Response(
            200,
            json=response(
                [first, bse] if status == "open" else [announced] if status == "announced" else []
            ),
        )

    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts(
            "test-secret", transport=httpx.MockTransport(handler), sleep=no_sleep
        ),
    )

    async def no_exchange(url):
        from packages.providers.exchanges import NSE_IPO

        assert url == NSE_IPO  # Independent subscriptions remain enabled.
        return b"[]"

    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run, no_exchange)
    assert run.status == "SUCCESS", run.counters
    public = [c for c in await catalog(db) if not c["is_demo"]]
    assert len(public) == 3
    issue = next(c for c in public if c["ticker"] == "FIXTURE")
    assert issue["provider_details"]["about"] == "Provider business description."
    assert issue["price_high"] == 99 and issue["exchange"] == "NSE"
    assert next(c for c in public if c["ticker"] == "BSEFIX")["exchange"] == "BSE"
    assert next(c for c in public if c["ticker"] == "ANNOUNCED")["board"] == "Unknown"
    assert await db.scalar(select(func.count()).select_from(m.IPOProviderDetail)) == 3
    retry = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, retry, no_exchange)
    assert retry.counters["written"] == 0
    # Switching to the selected provider updates the existing master, not its public slug.
    ipo = await db.get(m.IPO, issue["ipo_id"])
    ipo.source_provider = "NSE"
    ipo.source_timestamp = datetime.now(UTC) - timedelta(days=1)
    first["priceRange"] = "100-105"
    again = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, again, no_exchange)
    assert again.status == "SUCCESS", again.counters
    assert ipo.price_high == 105 and ipo.source_provider == "IPOALERTS"
    assert (await db.get(m.Company, issue["id"])).slug == "provider-fixture"
    assert await db.scalar(select(func.count()).select_from(m.IPOProviderDetail)) == 3


async def test_auth_error_is_in_admin_job_log_and_keeps_masters(db, admin_client, monkeypatch):
    from packages.providers import ipo as registry

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts(
            "test-secret",
            transport=httpx.MockTransport(lambda r: httpx.Response(401)),
            sleep=no_sleep,
        ),
    )
    before = await db.scalar(select(func.count()).select_from(m.IPO))
    run = await create_run(db, "sync-ipos", "manual")
    await run_pipeline(db, run)
    assert run.status == "FAILED"
    error = await db.scalar(select(m.JobError).where(m.JobError.run_id == run.id))
    assert error.code == "IPOALERTS_AUTH_FAILED" and "API key" in error.detail
    assert await db.scalar(select(func.count()).select_from(m.IPO)) == before
    response_data = await admin_client.get("/api/v1/admin/market/errors")
    assert "IPOALERTS_AUTH_FAILED" in response_data.text and "test-secret" not in response_data.text
    status = await admin_client.get("/api/v1/admin/market")
    assert "IPOALERTS" in status.text and "test-secret" not in status.text


async def test_legacy_nse_mirror_mapping_requires_symbol_name_board_and_dates(db):
    from apps.worker.market import ingest_record, match_company
    from packages.providers.market import Issue

    mapped = normalize(row(), datetime.now(UTC) - timedelta(days=1))
    mapped.update(provider_namespace=None, provider_id=None, nse_symbol=None, bse_symbol="FIXTURE")
    original = Issue.model_validate(mapped)
    await ingest_record(db, "ipos", original, "NSE", "BSE", None)
    await db.flush()
    incoming = Issue.model_validate(normalize(row(), datetime.now(UTC)))
    company = await match_company(db, incoming)
    assert company is not None
    incoming.issue.close_date += timedelta(days=1)
    assert await match_company(db, incoming) is None
    incoming.issue.close_date -= timedelta(days=1)
    incoming.issue.name = "Another company"
    assert await match_company(db, incoming) is None


def test_dual_exchange_urls_bridge_source_changes_without_fabricated_scrip_code():
    item = row()
    item.update(
        source="bse",
        nseInfoUrl="https://www.nseindia.com/market-data/issue-information?symbol=FIXTURE",
        bseInfoUrl="https://www.bseindia.com/markets/publicIssues/DisplayIPO?IPONo=12345",
    )
    data = normalize(item, datetime.now(UTC))
    assert data["nse_symbol"] == data["bse_symbol"] == "FIXTURE"
    assert data["bse_issue_id"] == "12345" and data["bse_code"] is None
    item["nseInfoUrl"] = "https://www.nseindia.com/market-data/issue-information?symbol=OTHER"
    with pytest.raises(ValueError):
        normalize(item, datetime.now(UTC))


async def test_provider_identifier_never_replaces_public_ticker(db):
    from apps.worker.market import ingest_record
    from packages.providers.market import Issue

    item = row()
    item.update(
        source="bse",
        nseInfoUrl="https://www.nseindia.com/market-data/issue-information?symbol=FIXTURE",
        bseInfoUrl="https://www.bseindia.com/markets/publicIssues/DisplayIPO?IPONo=12345",
    )
    await ingest_record(
        db,
        "ipos",
        Issue.model_validate(normalize(item, datetime.now(UTC))),
        "IPOALERTS",
        "LICENSED",
        None,
    )
    await db.flush()
    public = next(c for c in await catalog(db) if c["name"] == item["name"])
    assert public["ticker"] == "FIXTURE" and public["exchange"] == "NSE"


async def test_bad_row_reports_field_path_without_losing_good_rows():
    bad = row()
    bad.update(id="bad-record", minQty=0)
    batches = [
        batch
        async for batch in IPOAlerts(
            "test-secret", transport=transport_for([row(), bad]), sleep=no_sleep
        ).batches(time.monotonic() + 60)
    ]
    assert len(batches[0].records) == 1
    assert "bad-record:issue.lot_size" in batches[0].errors[0][0]
    assert batches[0].errors[0][1] == "IPOALERTS_INVALID_ROW"
    assert "test-secret" not in str(batches[0].errors)

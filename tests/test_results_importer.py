from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from apps.api.repository import journey
from apps.worker import results as worker
from packages.database import models as m
from packages.providers import results as feed

XML = Path("tests/fixtures/nse-results-pranav-20261001.xml").read_bytes()
IDENTIFIERS = {"NSE": {"PRANAV"}, "BSE": {"544909"}, "ISIN": {"INE0H4201019"}}
CSV = b'522105,"Birla Precision Technologies Ltd",MQ2025-2026,Audited,Oct  4 2026  1:28PM\n522105,Birla Precision Technologies Ltd,MC2025-2026,Audited,Oct  4 2026  1:28PM\n'


def test_real_nse_units_and_contexts():
    rows = feed.parse_xbrl(XML, IDENTIFIERS, "CONSOLIDATED", "2026-06-30")
    assert len(rows) == 1
    assert rows[0]["facts"]["revenue"] == "1645400000"
    assert rows[0]["facts"]["pat"] == "143760000"
    assert rows[0]["facts"]["basic_eps"] == "1.65"
    assert rows[0]["period_type"] == "QUARTERLY"


def test_bse_discovery_codes_and_html_errors():
    rows = feed.bse_csv(b"\xef\xbb\xbfScrip Code,Name,Period,Audit,Date\n" + CSV + b"\n")
    assert len(rows) == 2
    assert rows[0]["reporting_code"] != rows[1]["reporting_code"]
    assert rows[0]["identifier"] == "522105"
    assert "period_end" not in rows[0]
    assert rows[0]["attachments"] == []
    with pytest.raises(feed.SourceError):
        feed.bse_csv(b"<html>Access denied</html>")


@pytest.mark.parametrize(
    "end,period",
    [(b"2026-09-30", "HALF_YEARLY"), (b"2026-12-31", "NINE_MONTH"), (b"2027-03-31", "ANNUAL")],
)
def test_period_durations_never_fabricate_quarters(end, period):
    rows = feed.parse_xbrl(XML.replace(b"2026-06-30", end), IDENTIFIERS)
    assert len(rows) == 1 and rows[0]["period_type"] == period


@pytest.mark.parametrize(
    "content,error",
    [
        (XML.replace(b"INE0H4201019", b"INE000A01010"), "FILING_COMPANY_MISMATCH"),
        (XML.replace(b"iso4217:INR", b"iso4217:USD"), "FINANCIAL_UNIT_REVIEW_REQUIRED"),
        (b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]>' + XML, "UNSAFE_XML"),
    ],
)
def test_reject_corrupt_identity_units_entities(content, error):
    with pytest.raises(feed.SourceError, match=error):
        feed.parse_xbrl(content, IDENTIFIERS)


def test_nil_is_not_zero_and_basis_is_validated():
    content = XML.replace(
        b'<in-capmkt:RevenueFromOperations contextRef="OneD" decimals="-5" unitRef="INR">1645400000</in-capmkt:RevenueFromOperations>',
        b'<in-capmkt:RevenueFromOperations xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true" contextRef="OneD"/>',
    )
    assert feed.parse_xbrl(content, IDENTIFIERS)[0]["facts"]["revenue"] is None
    with pytest.raises(feed.SourceError, match="FILING_BASIS_MISMATCH"):
        feed.parse_xbrl(XML, IDENTIFIERS, "STANDALONE")


async def test_sessions_redirect_scope_and_block():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/corporates/comp_results":
            return httpx.Response(
                302, headers={"location": "/ready", "set-cookie": "session=test; Path=/; Secure"}
            )
        if request.url.path == "/ready":
            assert request.headers.get("cookie") == "session=test"
            return httpx.Response(200, text="landing")
        assert "cookie" not in request.headers  # no leaking www host cookies to api host
        return httpx.Response(403)

    async with feed.ExchangeSession("BSE", httpx.MockTransport(handle)) as session:
        await session.initialize()
        with pytest.raises(feed.SourceError, match="SOURCE_HTTP_403"):
            await session.get(feed.BSE_TODAY)
    assert len(calls) == 3


async def test_redirect_host_and_retry_after():
    async with feed.ExchangeSession(
        "NSE",
        httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        ),
    ) as session:
        with pytest.raises(feed.FeedError, match="UNAPPROVED_EXCHANGE_URL"):
            await session.get(feed.NSE_RESULTS)
    async with feed.ExchangeSession(
        "NSE", httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "3600"}))
    ) as session:
        with pytest.raises(feed.SourceError) as error:
            await session.get(feed.NSE_RESULTS)
        assert error.value.retry_at > m.now() + timedelta(minutes=59)


async def tracked(db):
    company = m.Company(slug="pranav-test", name="Pranav test", isin="INE0H4201019", is_demo=False)
    db.add(company)
    await db.flush()
    db.add(m.IPO(company_id=company.id, status="LISTED"))
    db.add_all(
        [
            m.Identifier(company_id=company.id, exchange=ex, ticker=next(iter(IDENTIFIERS[ex])))
            for ex in ("NSE", "BSE")
        ]
    )
    await db.commit()
    return company


def metadata(exchange="NSE", stamp="2026-10-01T20:19:04+05:30"):
    return {
        "identifier": "PRANAV" if exchange == "NSE" else "544909",
        "announced_at": stamp,
        "basis": "CONSOLIDATED",
        "period_end": "2026-06-30",
        "source_url": feed.NSE_RESULTS if exchange == "NSE" else feed.BSE_TODAY,
        "attachments": ["https://nsearchives.nseindia.com/corporate/test.xml"],
    }


async def test_publication_idempotency_revision_conflict_and_public_api(db):
    company = await tracked(db)
    filing, created = await worker.store_filing(db, "NSE", metadata())
    assert created
    assert not (await worker.store_filing(db, "NSE", metadata()))[1]
    parsed = await worker.preview(db, filing, XML)
    assert await worker.publish(db, filing, parsed) == 1
    assert await worker.publish(db, filing, parsed) == 0
    other, _ = await worker.store_filing(db, "BSE", metadata("BSE"))
    assert await worker.publish(db, other, parsed) == 0
    row = await db.scalar(
        select(m.FinancialResult).where(m.FinancialResult.company_id == company.id)
    )
    assert len(row.provenance) == 2
    updated, _ = await worker.store_filing(db, "NSE", metadata(stamp="2026-10-02T20:00:00+05:30"))
    revised = await worker.preview(db, updated, XML.replace(b"1645400000", b"1645500000"))
    assert await worker.publish(db, updated, revised) == 1
    await db.commit()
    with pytest.raises(feed.SourceError, match="OLDER_OR_CONFLICTING_REVISION"):
        await worker.publish(db, filing, parsed)
    with pytest.raises(feed.SourceError, match="CROSS_EXCHANGE_CONFLICT"):
        await worker.publish(db, other, parsed)
    company_data = await journey(db, company.slug)
    current = company_data["financial_performance"]["items"]
    assert len(current) == 1 and current[0]["revision"] == 2
    assert current[0]["facts"]["revenue"] == "1645500000"
    assert company_data["latest"]["revenue"] == 164.55
    assert company_data["latest"]["eps"] == 1.65
    assert company_data["latest"]["label"] == "Q1 FY27"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(m.FinancialResult)
            .where(m.FinancialResult.company_id == company.id)
        )
        == 2
    )


async def test_admin_preview_then_publish_and_auth(admin_client, db):
    await tracked(db)
    response = await admin_client.post(
        "/api/v1/admin/results/filings",
        json={"exchange": "NSE", **{k: v for k, v in metadata().items() if k != "attachments"}},
    )
    assert response.status_code == 200, response.text
    filing = response.json()
    response = await admin_client.post(
        f"/api/v1/admin/results/filings/{filing['id']}/preview", content=XML
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["publishable"]
    assert await db.scalar(select(func.count()).select_from(m.FinancialResult)) == 0
    response = await admin_client.post(
        "/api/v1/admin/results/publish", json={k: result[k] for k in ("attachment_id", "checksum")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["published"] == 1
    assert (
        await admin_client.get("/api/v1/admin/results/attachments/" + result["attachment_id"])
    ).content == XML


async def test_private_endpoints_require_auth(client):
    assert (await client.get("/api/v1/admin/results")).status_code == 401


async def test_exchange_failure_isolated(db):
    from apps.worker.market import create_run

    await tracked(db)
    run = await create_run(db, "sync-results", "manual")

    class Session:
        def __init__(self, exchange):
            self.exchange = exchange

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            if self.exchange == "BSE":
                raise feed.SourceError("SOURCE_ACCESS_BLOCKED")

        async def get(self, url):
            return b'{"data":[],"totalCount":0}'

    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    await worker.sync(db, run, counts, Session)
    assert counts["providers"] == 1 and counts["failed"] == 0
    assert counts["skipped_nse_companies"] == 1
    bse, nse = await db.get(m.ResultSource, "BSE"), await db.get(m.ResultSource, "NSE")
    assert bse.last_success is None
    assert nse.last_success is not None


def test_real_sme_half_year_keeps_reported_duration_and_units():
    content = Path("tests/fixtures/nse-results-manav-halfyear.xml").read_bytes()
    rows = feed.parse_xbrl(
        content,
        {"NSE": {"MANAV"}, "BSE": set(), "ISIN": {"INE104Y01012"}},
        "STANDALONE",
        "2025-09-30",
    )
    assert len(rows) == 1
    assert rows[0]["period_type"] == "HALF_YEARLY"
    assert rows[0]["facts"]["revenue"] == "94288000"
    assert rows[0]["facts"]["pat"] == "4132000"
    assert rows[0]["facts"]["basic_eps"] == "0.31"


async def test_nse_pagination_both_boards_and_repeated_page_rejection():
    import json

    class Session:
        def __init__(self, repeat=False):
            self.calls = []
            self.repeat = repeat

        async def get(self, url):
            from urllib.parse import parse_qs, urlsplit

            params = parse_qs(urlsplit(url).query)
            self.calls.append(params)
            if params.get("index") == ["sme"]:
                return b'{"data":[],"totalCount":0}'
            page = int(params["page"][0])
            indices = range(100) if page == 1 or self.repeat else [100]
            rows = [
                {
                    "symbol": "PRANAV",
                    "seq_Id": str(i),
                    "creation_Date": "01-Oct-2026 20:19:04",
                    "consolidated": "Consolidated",
                    "qe_Date": "30-JUN-2026",
                    "xbrl": "https://nsearchives.nseindia.com/corporate/file.xml",
                }
                for i in indices
            ]
            return json.dumps({"data": rows, "totalCount": 101}).encode()

    session = Session()
    assert len(await feed.discover_nse(session, date(2026, 9, 1), date(2026, 10, 5))) == 101
    assert len(session.calls) == 3 and session.calls[-1]["index"] == ["sme"]
    with pytest.raises(feed.SourceError, match="SOURCE_INCOMPLETE_DISCOVERY"):
        await feed.discover_nse(Session(True), date(2026, 9, 1), date(2026, 10, 5))


async def test_bse_history_uses_returned_links_not_quarter_guesses():
    import json

    class Session:
        async def get(self, url):
            assert "qtr=" not in url and "SCRIP_CD=544909" in url
            return json.dumps(
                {
                    "Table": [
                        {
                            "Scrip_cd": "544909",
                            "XMLName": "returned-one.xml",
                            "Consol_XMLName": "returned-two.xml",
                            "Resultpageurl": "results?Code=544909&qtr=observed&RType=c",
                        }
                    ]
                }
            ).encode()

    rows = await feed.discover_bse_history(Session(), "544909")
    assert [r["basis"] for r in rows] == ["STANDALONE", "CONSOLIDATED"]
    assert rows[1]["attachments"] == ["https://www.bseindia.com/XBRLFILES/returned-two.xml"]


async def test_bse_manual_fixture_reaches_tracker_without_cross_exchange_sum(db):
    company = await tracked(db)
    filing, _ = await worker.store_filing(db, "BSE", metadata("BSE"))
    await worker.store_attachment(db, filing, XML, "https://www.bseindia.com/XBRLFILES/fixture.xml")
    assert await worker.publish(db, filing, await worker.preview(db, filing, XML)) == 1
    await db.commit()
    result = await journey(db, company.slug)
    assert result["latest"]["source_provider"] == "BSE"
    assert result["latest"]["revenue"] == 164.54


async def test_half_year_public_result_does_not_become_tracker_quarter(db):
    company = m.Company(slug="manav-test", name="Manav test", isin="INE104Y01012", is_demo=False)
    db.add(company)
    await db.flush()
    db.add(m.IPO(company_id=company.id, status="LISTED"))
    db.add(m.Identifier(company_id=company.id, exchange="NSE", ticker="MANAV"))
    await db.commit()
    filing, _ = await worker.store_filing(
        db,
        "NSE",
        {**metadata(), "identifier": "MANAV", "basis": "STANDALONE", "period_end": "2025-09-30"},
    )
    content = Path("tests/fixtures/nse-results-manav-halfyear.xml").read_bytes()
    await worker.publish(db, filing, await worker.preview(db, filing, content))
    await db.commit()
    result = await journey(db, company.slug)
    assert result["financial_performance"]["items"][0]["period_type"] == "HALF_YEARLY"
    assert not result["quarters"]


async def test_history_checkpoint_and_retry_after_are_persistent(db):
    from apps.worker.market import create_run

    company = await tracked(db)
    run = await create_run(
        db,
        "sync-results",
        "reconciliation",
        {
            "company_id": company.id,
            "history": True,
            "from": "2022-10-05",
            "to": "2026-10-05",
            "exchanges": ["NSE"],
        },
    )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def get(self, url):
            return b'{"data":[],"totalCount":0}'

    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    await worker.sync(db, run, counts, lambda ex: Session())
    checkpoint = await db.get(m.ResultHistory, {"company_id": company.id, "exchange": "NSE"})
    assert checkpoint.from_date == date(2022, 10, 5)
    state = await db.get(m.ResultSource, "NSE")
    assert state.reconciled_at is not None
    state.retry_at = m.now() + timedelta(hours=1)
    await db.commit()

    def forbidden(exchange):
        raise AssertionError("Must honor persistent retry deadline")

    await worker.sync(db, run, counts, forbidden)
    assert counts["failed"] == 1

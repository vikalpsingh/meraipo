import json
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from apps.worker import results as worker
from apps.worker.market import create_run
from packages.database import models as m
from packages.providers import bse_results
from packages.providers import results as feed
from packages.providers.company_results import approved_url, public_address
from tests.test_results_importer import XML, metadata, tracked


def announcement(**changes):
    return {
        "NEWSID": "filing-1",
        "SCRIP_CD": 544909,
        "CATEGORYNAME": "Result",
        "SUBCATNAME": "Financial Results",
        "NEWSSUB": "Financial Results",
        "DT_TM": "2026-10-01T20:19:04",
        "ATTACHMENTNAME": "result.xml",
        "OLD": 1,
        **changes,
    }


def response(rows, total=None):
    return {"Table": rows, "Table1": [{"ROWCNT": len(rows) if total is None else total}]}


async def test_landing_denial_does_not_abort_api_and_diagnostics_are_sanitized():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "www.bseindia.com":
            return httpx.Response(
                406,
                headers={
                    "content-type": "text/html",
                    "x-request-id": "ref-123",
                    "set-cookie": "secret=hide",
                },
                text="<html>Access denied token=hide</html>",
            )
        assert "cookie" not in request.headers
        assert request.headers["sec-fetch-site"] == "same-site"
        return httpx.Response(200, text="Scrip Code,Company,Period,Audit,Date\n")

    async with feed.ExchangeSession("BSE", httpx.MockTransport(handle)) as session:
        await session.initialize()
        assert feed.bse_csv(await session.get(feed.BSE_TODAY)) == []
        event = session.events[0]
        assert event["status"] == 406 and event["stage"] == "session_initialization"
        assert event["references"] == {"x-request-id": "ref-123"}
        assert "hide" not in json.dumps(event)
        assert len(calls) == 2


@pytest.mark.parametrize("status", [403, 406, 429])
async def test_discovery_and_attachment_denials_are_distinct_and_not_retried(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "60"}, text="Denied")

    async with feed.ExchangeSession("BSE", httpx.MockTransport(handle)) as session:
        for url, stage in [
            (bse_results.ANNOUNCEMENTS, "company_announcements"),
            ("https://www.bseindia.com/XBRLFILES/real.xml", "attachment_download"),
        ]:
            with pytest.raises(feed.SourceError) as error:
                await session.get(url)
            assert error.value.diagnostic["status"] == status
            assert error.value.diagnostic["stage"] == stage
            assert error.value.retry_at if status == 429 else not error.value.retry_at
        assert len(calls) == 2


async def test_announcement_pagination_filtering_and_returned_archive_paths():
    class Session:
        async def get(self, url):
            if "pageno=1&" in url:
                return json.dumps(
                    response(
                        [
                            announcement(
                                NEWSID="notice",
                                CATEGORYNAME="Board Meeting",
                                NEWSSUB="Board Meeting Intimation for Financial Results",
                            )
                        ],
                        2,
                    )
                ).encode()
            return json.dumps(
                response(
                    [announcement(ATTACHMENTNAME="/xml-data/corpfiling/AttachHis/actual.xml")], 2
                )
            ).encode()

    rows = await bse_results.discover(Session(), "544909", date(2026, 9, 1), date(2026, 10, 10))
    assert len(rows) == 1
    assert rows[0]["attachments"] == [
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/actual.xml"
    ]
    assert "period_end" not in rows[0]
    assert bse_results.is_result(
        announcement(CATEGORYNAME="Company Update", NEWSSUB="Integrated Filing (Financial)")
    )


async def test_complete_empty_and_repeated_pages():
    class Empty:
        async def get(self, url):
            return json.dumps(response([])).encode()

    assert await bse_results.discover(Empty(), "544909", date.today(), date.today()) == []

    class Repeated:
        async def get(self, url):
            return json.dumps(response([announcement()], 2)).encode()

    with pytest.raises(feed.SourceError, match="SOURCE_INCOMPLETE_DISCOVERY"):
        await bse_results.discover(Repeated(), "544909", date.today(), date.today())


async def test_bse_only_end_to_end_and_idempotent_revisions(db):
    from sqlalchemy import delete

    company = await tracked(db)
    await db.execute(
        delete(m.Identifier).where(
            m.Identifier.company_id == company.id, m.Identifier.exchange == "NSE"
        )
    )
    await db.commit()
    revised = False

    def handle(request):
        path = request.url.path
        if "comp_results" in path:
            return httpx.Response(403)
        if "NSToday" in path:
            return httpx.Response(200, text="Scrip Code,Name,Period,Audit,Date\n")
        if "AnnSubCategory" in path:
            row = announcement(DT_TM="2026-10-02T20:19:04" if revised else "2026-10-01T20:19:04")
            return httpx.Response(200, json=response([row]))
        if "Corp_Finance" in path:
            return httpx.Response(200, json={"Table": []})
        return httpx.Response(
            200, content=XML.replace(b"1645400000", b"1645500000") if revised else XML
        )

    def session(exchange):
        return feed.ExchangeSession(exchange, httpx.MockTransport(handle))

    async def run():
        job = await create_run(db, "sync-results-bse", "manual", {"exchanges": ["BSE"]})
        counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
        await worker.sync(db, job, counts, session)
        return counts

    first = await run()
    assert first["downloaded"] == first["published"] == 1
    assert (await run())["downloaded"] == 0
    revised = True
    assert (await run())["published"] == 1
    assert await db.scalar(select(func.count()).select_from(m.FinancialResult)) == 2
    public = await worker.public_results(db, company.id)
    assert public["items"][0]["facts"]["revenue"] == "1645500000"
    assert public["items"][0]["basis"] == "CONSOLIDATED"
    assert public["items"][0]["period_type"] == "QUARTERLY"
    assert await db.scalar(select(func.count()).select_from(m.ResultDiagnostic)) > 0


async def test_bse_skips_nse_companies_and_their_pending_attachments(db):
    await tracked(db)
    filing, _ = await worker.store_filing(db, "BSE", metadata("BSE"))
    await db.commit()
    job = await create_run(db, "sync-results-bse", "manual", {"exchanges": ["BSE"]})

    def forbidden(exchange):
        raise AssertionError("NSE companies must never be fetched by BSE")

    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    await worker.sync(db, job, counts, forbidden)
    assert counts["skipped_nse_companies"] == 1
    assert filing.status == "AWAITING_PROCESSING"


async def test_bse_retry_after_also_defers_pending_downloads(db):
    from datetime import timedelta

    from sqlalchemy import delete

    company = await tracked(db)
    await db.execute(
        delete(m.Identifier).where(
            m.Identifier.company_id == company.id, m.Identifier.exchange == "NSE"
        )
    )
    await worker.store_filing(db, "BSE", metadata("BSE"))
    db.add(
        m.ResultSource(
            exchange="BSE",
            enabled=True,
            status="SOURCE_RATE_LIMITED",
            retry_at=m.now() + timedelta(hours=1),
        )
    )
    await db.commit()
    job = await create_run(db, "sync-results-bse", "manual", {"exchanges": ["BSE"]})

    def forbidden(exchange):
        raise AssertionError("Retry-After must defer discovery and attachment requests")

    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    await worker.sync(db, job, counts, forbidden)
    assert counts["downloaded"] == 0
    assert counts["failed"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://127.0.0.1/",
        "https://169.254.169.254/",
        "https://host.local/",
        "https://user:pass@example.com/",
        "https://example.com/%2e%2e/private",
    ],
)
def test_official_source_url_rejects_unsafe_targets(url):
    with pytest.raises(feed.SourceError):
        approved_url(url)


async def test_official_source_dns_rejects_private_addresses(monkeypatch):
    import asyncio

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(feed.SourceError):
        await public_address("https://company.example/results/")


async def test_official_source_approval_and_nse_exclusion(admin_client, db, monkeypatch):
    from sqlalchemy import delete

    from packages.providers import company_results

    company = await tracked(db)
    payload = {
        "page_url": "https://company.example/results/",
        "document_prefix": "https://company.example/files/",
        "enabled": True,
        "official_source_confirmed": True,
    }
    endpoint = f"/api/v1/admin/results/official-sources/{company.id}"
    assert (await admin_client.put(endpoint, json=payload)).status_code == 422
    await db.execute(
        delete(m.Identifier).where(
            m.Identifier.company_id == company.id, m.Identifier.exchange == "NSE"
        )
    )
    await db.commit()

    async def public(url):
        return "93.184.216.34"

    monkeypatch.setattr(company_results, "public_address", public)
    assert (
        await admin_client.put(endpoint, json={**payload, "official_source_confirmed": False})
    ).status_code == 422
    assert (await admin_client.put(endpoint, json=payload)).status_code == 200
    source = await db.get(m.CompanyResultSource, company.id)
    assert source.approved_by and source.enabled
    assert (
        await admin_client.put(
            endpoint, json={**payload, "document_prefix": "https://evil.example/files/"}
        )
    ).status_code == 422


async def test_official_links_pin_public_ip_and_keep_unverified_dates_in_review(db, monkeypatch):
    from packages.providers import company_results

    await tracked(db)

    async def public(url):
        return "93.184.216.34"

    monkeypatch.setattr(company_results, "public_address", public)

    def handle(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "company.example"
        assert request.extensions["sni_hostname"] == "company.example"
        if request.url.path == "/results/":
            return httpx.Response(
                200,
                text='<a href="/files/results.xml">Results</a><a href="https://evil.example/results.xml">Other</a>',
            )
        return httpx.Response(200, content=XML)

    async with company_results.CompanySession(
        "https://company.example/results/",
        "https://company.example/files/",
        httpx.MockTransport(handle),
    ) as session:
        urls = await company_results.discover(session)
        assert urls == ["https://company.example/files/results.xml"]
        filing, _ = await worker.store_filing(
            db,
            "BSE",
            {
                "identifier": "544909",
                "attachments": urls,
                "origin": "OFFICIAL_COMPANY",
                "source_url": session.page_url,
            },
        )
        counts = dict(downloaded=0, parsed=0, published=0, failed=0)
        await worker.process(db, filing, session, counts)
        assert counts["downloaded"] == 1 and counts["published"] == 0
        assert filing.error == "FILING_TIMESTAMP_REVIEW_REQUIRED"
        assert await db.scalar(select(func.count()).select_from(m.ResultAttachment)) == 1


async def test_downloaded_bse_pdf_is_reported_as_review_not_publication(db):
    from sqlalchemy import delete

    company = await tracked(db)
    await db.execute(
        delete(m.Identifier).where(
            m.Identifier.company_id == company.id, m.Identifier.exchange == "NSE"
        )
    )
    await db.commit()

    def handle(request):
        if "comp_results" in request.url.path:
            return httpx.Response(200, text="landing")
        if "NSToday" in request.url.path:
            return httpx.Response(200, text="Scrip Code,Name,Period,Audit,Date\n")
        if "AnnSubCategory" in request.url.path:
            return httpx.Response(200, json=response([announcement(ATTACHMENTNAME="results.pdf")]))
        if "Corp_Finance" in request.url.path:
            return httpx.Response(200, json={"Table": []})
        return httpx.Response(200, content=b"%PDF-1.7 synthetic review fixture")

    job = await create_run(db, "sync-results-bse", "manual", {"exchanges": ["BSE"]})
    counts = dict(fetched=0, written=0, unchanged=0, failed=0, providers=0)
    await worker.sync(
        db, job, counts, lambda ex: feed.ExchangeSession(ex, httpx.MockTransport(handle))
    )
    assert counts["downloaded"] == counts["review_required"] == counts["failed"] == 1
    assert counts["published"] == 0 and counts["providers"] == 1
    assert (await db.scalar(select(m.JobError))).code == "PARSING_REVIEW_REQUIRED"

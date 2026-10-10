"""Official IR fallback feeds the same original retention and conservative parser."""

import asyncio

from sqlalchemy import select

from packages.database import models as m
from packages.providers.company_results import CompanySession, discover
from packages.shared.calculations import utc


async def sync_official_sources(db, run, counts, company_ids):
    from apps.worker import results as worker
    from apps.worker.bse_results import drain, event, failure
    sources = (await db.scalars(select(m.CompanyResultSource).where(m.CompanyResultSource.company_id.in_(company_ids), m.CompanyResultSource.enabled.is_(True)))).all()
    if not sources:
        event(db, run, "official_company_discovery", "NO_APPROVED_SOURCE")
        await db.commit()
        return
    try:
        async with asyncio.timeout(35):
            for source in sources:
                async with CompanySession(source.page_url, source.document_prefix) as session:
                    try:
                        company = await db.get(m.Company, source.company_id)
                        identities = await worker.company_identifiers(db, company)
                        if identities["NSE"] or not identities["BSE"]:
                            continue
                        for url in await discover(session):
                            filing, created = await worker.store_filing(db, "BSE", {"identifier": sorted(identities["BSE"])[0], "origin": "OFFICIAL_COMPANY", "source_url": source.page_url, "attachments": [url]})
                            counts["fetched"] += 1
                            counts["unchanged"] += int(not created)
                            if not created and (filing.status not in ("AWAITING_PROCESSING", "DOWNLOAD_RETRY") or filing.retry_at and utc(filing.retry_at) > m.now()):
                                continue
                            # Identity/period/basis/units checked by the same parser. Unknown
                            # publication dates and PDFs remain in review, never auto-published.
                            await worker.process(db, filing, session, counts, run=run)
                    except Exception as exc:
                        failure(db, run, counts, "official_company_discovery", exc, source.company_id)
                    finally:
                        drain(db, run, session)
                        await db.commit()
    except TimeoutError as exc:
        failure(db, run, counts, "official_company_discovery", exc)
        await db.commit()

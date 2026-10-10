"""BSE-only results discovery. NSE-owned companies never enter this pipeline."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from packages.database import models as m
from packages.providers import bse_results as announcements
from packages.providers import results as feed
from packages.shared.calculations import utc


def event(db, run, stage, code, **evidence):
    db.add(m.ResultDiagnostic(run_id=run.id, exchange="BSE", stage=stage, code=code, evidence=evidence))


def drain(db, run, session):
    for item in getattr(session, "events", []):
        item = dict(item)
        stage, code = item.pop("stage"), item.pop("code")
        event(db, run, stage, code, **item)
    if hasattr(session, "events"):
        session.events.clear()


def failure(db, run, counts, stage, exc, company_id=None):
    from apps.worker.exchange_pipeline import error
    code = str(exc) if isinstance(exc, feed.FeedError) else "SOURCE_TIMEOUT" if isinstance(exc, TimeoutError) else type(exc).__name__
    counts["failed"] += 1
    error(db, run, "BSE", f"{stage} {company_id or ''}", exc if isinstance(exc, feed.FeedError) else feed.SourceError(code))
    event(db, run, stage, code, company_id=company_id)


async def sync_bse(db, run, counts, start, end, session_factory):
    from apps.worker import results as worker
    state = await db.get(m.ResultSource, "BSE")
    if not state:
        state = m.ResultSource(exchange="BSE", enabled=True, schedule="22:00", status="NOT_YET_RUN")
        db.add(state)
        await db.flush()
    if not state.enabled:
        return "BSE: SOURCE_DISABLED"
    nse_ids = set((await db.scalars(select(m.Identifier.company_id).where(m.Identifier.exchange == "NSE"))).all())
    mappings = (await db.scalars(select(m.Identifier).join(m.Company).where(m.Identifier.exchange == "BSE", m.Company.is_demo.is_(False)))).all()
    counts["skipped_nse_companies"] = len({r.company_id for r in mappings if r.company_id in nse_ids})
    mappings = [r for r in mappings if r.company_id not in nse_ids and (not run.parameters.get("company_id") or r.company_id == run.parameters["company_id"])]
    if not mappings:
        event(db, run, "scope", "NO_BSE_ONLY_COMPANIES", skipped_nse=counts["skipped_nse_companies"])
        await db.commit()
        return "BSE: NO_BSE_ONLY_COMPANIES"
    tracked = {r.ticker: r.company_id for r in mappings}
    company_ids = set(tracked.values())
    failures_before, completed = counts["failed"], 0
    throttled = state.retry_at and utc(state.retry_at) > m.now()
    if throttled:
        failure(db, run, counts, "results_list", feed.SourceError("SOURCE_RATE_LIMITED", state.retry_at))
    else:
        async with session_factory("BSE") as session:
            try:
                async with asyncio.timeout(110):
                    try:
                        await session.initialize()
                    except feed.FeedError:
                        pass  # Custom transports also may have an unavailable landing page.
                    drain(db, run, session)
                    try:
                        today_rows = feed.bse_csv(await session.get(feed.BSE_TODAY))
                        counts["discovered"] += len(today_rows)
                        # Today's CSV is only a discovery hint; it has no original attachment.
                        event(db, run, "results_list", "VALID_RESPONSE", rows=len(today_rows))
                    except feed.FeedError as exc:
                        failure(db, run, counts, "results_list", exc)
                        if exc.retry_at:
                            state.retry_at = exc.retry_at
                            raise
                    detail_available = True
                    for code, company_id in sorted(tracked.items()):
                        checkpoint = await db.get(m.ResultHistory, {"company_id": company_id, "exchange": "BSE"})
                        since = start
                        if checkpoint and not run.parameters.get("from"):
                            since = min(start, checkpoint.to_date - timedelta(days=3))
                        try:
                            rows = await announcements.discover(session, code, since, end)
                            counts["discovered"] += len(rows)
                            for metadata in rows:
                                _, created = await worker.store_filing(db, "BSE", metadata)
                                counts["matched"] += 1
                                counts["fetched"] += 1
                                counts["unchanged"] += int(not created)
                            # Only a complete, persisted announcement traversal advances recovery.
                            if not checkpoint:
                                checkpoint = m.ResultHistory(company_id=company_id, exchange="BSE")
                                db.add(checkpoint)
                            checkpoint.from_date, checkpoint.to_date, checkpoint.completed_at = since, end, m.now()
                            completed += 1
                            await db.commit()
                        except feed.FeedError as exc:
                            failure(db, run, counts, "company_announcements", exc, company_id)
                            if exc.retry_at:
                                state.retry_at = exc.retry_at
                            # Stop this endpoint after an access denial; still process other sources.
                            if str(exc) in ("SOURCE_HTTP_403", "SOURCE_HTTP_406", "SOURCE_RATE_LIMITED"):
                                break
                            continue
                        if not detail_available:
                            continue
                        try:
                            details = await feed.discover_bse_history(session, code)
                            for metadata in details:
                                if metadata["identifier"] != code:
                                    raise feed.SourceError("FILING_COMPANY_MISMATCH")
                                # Detail timestamps are not fabricated from fetch time.
                                _, created = await worker.store_filing(db, "BSE", metadata)
                                counts["fetched"] += 1
                                counts["unchanged"] += int(not created)
                        except feed.FeedError as exc:
                            failure(db, run, counts, "result_detail", exc, company_id)
                            if exc.retry_at:
                                state.retry_at = exc.retry_at
                                break
                            if str(exc) in ("SOURCE_HTTP_403", "SOURCE_HTTP_406"):
                                # The detail endpoint is optional; announcements continue independently.
                                event(db, run, "result_detail", "DETAIL_ROUTE_DISABLED_FOR_RUN")
                                detail_available = False
            except Exception as exc:
                failure(db, run, counts, "discovery", exc)
            finally:
                drain(db, run, session)
                state.status = "SUCCESS" if completed == len(tracked) and counts["failed"] == failures_before else "PARTIAL" if completed else "SOURCE_DISCOVERY_FAILED"
                if completed == len(tracked):
                    state.last_success = m.now()
                    counts["providers"] += 1
                await db.commit()
    pending = (await db.scalars(select(m.ResultFiling).where(m.ResultFiling.exchange == "BSE", m.ResultFiling.company_id.in_(company_ids), m.ResultFiling.status.in_(["AWAITING_PROCESSING", "DOWNLOAD_RETRY"])).order_by(m.ResultFiling.created_at).limit(15))).all()
    async with session_factory("BSE") as session:
        try:
            async with asyncio.timeout(55):
                for filing in pending:
                    if filing.metadata_json.get("origin") == "OFFICIAL_COMPANY":
                        continue
                    if filing.retry_at and utc(filing.retry_at) > m.now():
                        continue
                    await worker.process(db, filing, session, counts, run=run)
                    if filing.error:
                        from apps.worker.exchange_pipeline import error
                        error(db, run, "BSE", f"filing:{filing.id}", feed.SourceError(filing.error))
                    if filing.error in ("SOURCE_HTTP_403", "SOURCE_HTTP_406", "SOURCE_RATE_LIMITED"):
                        break
        except Exception as exc:
            failure(db, run, counts, "attachment_download", exc)
        finally:
            drain(db, run, session)
            await db.commit()
    # Official, approved company pages remain independent of exchange availability.
    from apps.worker.company_results import sync_official_sources
    await sync_official_sources(db, run, counts, company_ids)
    return None

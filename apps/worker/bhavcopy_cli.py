"""Operate the same Daily closing price sync used by admin and Celery."""

import argparse
import asyncio
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from apps.worker.bhavcopy import cleanup, preview, save_original
from apps.worker.market import create_run, india_today, run_job
from packages.database import models as m
from packages.database.session import Session, engine
from packages.providers.bhavcopy import MAX_DOWNLOAD, sources
from packages.shared.market_config import market_settings_context


async def main(args):
    try:
        async with Session() as db:
            if args.command == "configure":
                value = Path(args.file).read_text(encoding="utf-8-sig")
                sources(value)
                row = await db.get(m.MarketConfiguration, "market")
                if not row:
                    row = m.MarketConfiguration(id="market", values={})
                    db.add(row)
                row.values = {**row.values, "bhavcopy_sources_json": value}
                from apps.api.cache import commit_with_invalidation

                await commit_with_invalidation(db)
                print("Bhavcopy sources configured; scheduler enablement unchanged")
                return
            if args.command == "status":
                rows = (
                    await db.scalars(
                        select(m.BhavcopyFile).order_by(m.BhavcopyFile.created_at.desc()).limit(20)
                    )
                ).all()
                print(
                    json.dumps(
                        [
                            dict(
                                exchange=r.exchange,
                                date=str(r.trade_date),
                                status=r.status,
                                error=r.error,
                                counters=r.counters,
                            )
                            for r in rows
                        ]
                    )
                )
                return
            async with market_settings_context(db):
                failed = False
                start = args.date if args.command != "backfill" else args.from_date
                end = args.to_date if args.command == "backfill" else start
                if end > india_today() or not 0 <= (end - start).days <= 30:
                    raise ValueError("Choose at most 31 non-future dates")
                params = {"exchange": args.exchange} if args.exchange else {}
                if args.command == "upload":
                    path = Path(args.file)
                    if path.stat().st_size > MAX_DOWNLOAD:
                        raise ValueError("File exceeds 20 MB")
                    content = path.read_bytes()
                    rows, errors, counts = await preview(db, content, args.exchange, start)
                    print(json.dumps({"preview": counts, "errors": errors[:100]}, default=str))
                    if not args.apply:
                        return
                    await cleanup(db)
                    checksum = hashlib.sha256(content).hexdigest()
                    artifact = m.BhavcopyFile(
                        exchange=args.exchange,
                        trade_date=start,
                        source_url="manual-upload",
                        checksum=checksum,
                        path=save_original(content, args.exchange, start, checksum),
                        status="PREVIEW",
                        counters=counts,
                        errors=errors,
                    )
                    db.add(artifact)
                    await db.commit()
                    params["upload_id"] = artifact.id
                for offset in range((end - start).days + 1):
                    day = start + timedelta(days=offset)
                    run = await create_run(
                        db, "sync-prices", "manual", {**params, "trade_date": day.isoformat()}
                    )
                    await run_job(db, run)
                    failed = failed or run.status in ("FAILED", "PARTIAL")
                    print(
                        json.dumps(
                            {
                                "id": run.id,
                                "date": str(day),
                                "status": run.status,
                                "counters": run.counters,
                                "error": run.error,
                            }
                        )
                    )
                if failed:
                    raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    configure = commands.add_parser("configure")
    configure.add_argument("--file", required=True)
    for name in ("sync", "backfill", "upload"):
        command = commands.add_parser(name)
        command.add_argument("--exchange", choices=["NSE", "BSE"], required=name == "upload")
        if name == "backfill":
            command.add_argument("--from-date", type=date.fromisoformat, required=True)
            command.add_argument("--to-date", type=date.fromisoformat, required=True)
        else:
            command.add_argument("--date", type=date.fromisoformat, required=True)
        if name == "upload":
            command.add_argument("--file", required=True)
            command.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))

"""Queue the same durable jobs used by admin and cron; does not bypass worker controls."""

import argparse
import asyncio
import json

from apps.api.market_routes import RunRequest, dispatch
from packages.database.session import Session, engine


async def main(args):
    try:
        async with Session() as db:
            result = await dispatch(
                db,
                args.job,
                "manual",
                RunRequest(
                    company_id=args.company_id,
                    from_date=args.from_date,
                    to_date=args.to_date,
                    confirm_backfill=args.confirm_backfill,
                    retry_rejected=args.retry_rejected,
                ),
            )
            print(json.dumps(result))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from apps.api.market_routes import ALL_JOBS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=list(ALL_JOBS))
    parser.add_argument("--company-id")
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--confirm-backfill", action="store_true")
    parser.add_argument("--retry-rejected", action="store_true")
    asyncio.run(main(parser.parse_args()))

"""Apply the agreed schedule only to a local development database.
Run: python -m scripts.set_dev_ipo_schedule
Never invoked by production startup or deployment.
"""

import asyncio

from sqlalchemy.engine import make_url

from packages.shared.config import settings


async def main():
    config = settings()
    url = make_url(config.database_url)
    if config.environment != "development" or (
        url.get_backend_name() != "sqlite" and url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError(
            "Only a local development database is allowed; production settings are never changed."
        )
    from packages.database import models as m
    from packages.database.session import Session

    async with Session() as db:
        row = await db.get(m.SchedulerControl, "sync-ipos")
        if row is None:
            row = m.SchedulerControl(name="sync-ipos")
            db.add(row)
        row.paused = False
        row.frequency = "hourly"
        row.schedule_times = ["00:30"]
        row.interval_hours = 12
        row.weekday = 0
        row.saturday_enabled = False
        row.sunday_enabled = False
        await db.commit()
    print("Saved development IPO schedule: weekdays 00:30 and 12:30 IST; weekends disabled.")


if __name__ == "__main__":
    asyncio.run(main())

"""Disposable SQLite-backed API for browser tests, never a production server."""

import os
import sys
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
(root / "work").mkdir(exist_ok=True)
db_path = root / "work" / f"e2e-{uuid4().hex}.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
os.environ["PUBLIC_ORIGIN"] = "http://127.0.0.1:3001"
os.environ["MARKET_FEEDS_JSON"] = "{}"
os.environ["EXCHANGE_DIRECT_ENABLED"] = "false"
os.environ["EXCHANGE_SOURCES_JSON"] = "[]"
os.environ["MARKET_SCHEDULER_ENABLED"] = "false"
os.environ["CRON_SECRET"] = ""
os.environ["TRADING_CALENDAR_YEAR"] = "0"

import asyncio

import uvicorn
from alembic import command
from alembic.config import Config

from apps.api.cli import change
from packages.database.seed import seed
from packages.database.session import Session, engine


async def prepare():
    async with Session() as db:
        await seed(db)
        from tests.market_browser_fixtures import seed_market_browser

        await seed_market_browser(db)
    await change("create_admin", "e2e@example.com", "test-only-browser-password-42")
    await engine.dispose()


if __name__ == "__main__":
    command.upgrade(Config(str(root / "alembic.ini")), "head")
    asyncio.run(prepare())
    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=8001, log_level="warning")

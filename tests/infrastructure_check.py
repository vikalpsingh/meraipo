"""Explicit PostgreSQL/Redis check required by the release gate."""

import asyncio
import os

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    url = os.environ["TEST_DATABASE_URL"]
    if not url.startswith("postgresql+") or not url.split("?")[0].endswith("/meraipo_test"):
        raise RuntimeError("Use an isolated PostgreSQL database named meraipo_test")
    engine = create_async_engine(url)
    async with engine.connect() as db:
        assert (await db.scalar(text("SELECT version()"))).startswith("PostgreSQL")
    await engine.dispose()
    redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    assert await redis.ping()
    await redis.set("meraipo:release-check", "ok", ex=10)
    assert await redis.get("meraipo:release-check") == b"ok"
    await redis.delete("meraipo:release-check")
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())

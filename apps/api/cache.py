import json

from redis.asyncio import Redis

from packages.shared.config import settings

client = Redis.from_url(
    settings().redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
)


async def cached(key, loader):
    try:
        if await client.exists("cache:dirty"):
            return await loader()
        generation = await client.get("cache:generation") or "0"
        cache_key = f"public:{generation}:{key}"
        value = await client.get(cache_key)
        if value:
            return json.loads(value)
    except Exception:
        cache_key = None
    data = await loader()
    if cache_key:
        try:
            await client.setex(cache_key, settings().cache_ttl, json.dumps(data, default=str))
        except Exception:
            pass
    return data


async def invalidate():
    try:
        await client.incr("cache:generation")
    except Exception:
        # A failed invalidation must not leave old cached generations reusable.
        # Reads are bounded by TTL; surface write-side degradation to callers.
        return False
    return True


async def commit_with_invalidation(db):
    """Serialize commit/invalidation; bypass cache through failure recovery."""
    from fastapi import HTTPException
    from redis.exceptions import RedisError

    if settings().environment == "test":
        await db.commit()
        return
    try:
        async with client.lock("cache:writer", timeout=120, blocking_timeout=5):
            await client.set("cache:dirty", "1", ex=max(settings().cache_ttl * 2, 300))
            await db.commit()
            if await invalidate():
                await client.delete("cache:dirty")
    except RedisError as exc:
        # If a post-commit Redis failure occurs, the dirty marker outlives all old entries.
        raise HTTPException(
            503, "Cache coordination failed. Refresh the record before retrying."
        ) from exc

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.api import cache, security


async def test_dirty_cache_bypasses_old_values(monkeypatch):
    fake = SimpleNamespace(exists=AsyncMock(return_value=True), get=AsyncMock())
    monkeypatch.setattr(cache, "client", fake)
    loader = AsyncMock(return_value={"new": True})
    assert await cache.cached("catalog", loader) == {"new": True}
    fake.get.assert_not_called()


async def test_cache_failure_reads_database(monkeypatch):
    fake = SimpleNamespace(exists=AsyncMock(side_effect=ConnectionError()))
    monkeypatch.setattr(cache, "client", fake)
    assert await cache.cached("catalog", AsyncMock(return_value=[])) == []


async def test_login_rate_limit_and_redis_outage_fail_closed(monkeypatch):
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    fake = SimpleNamespace(eval=AsyncMock(return_value=11))
    monkeypatch.setattr(security, "client", fake)
    with pytest.raises(HTTPException) as error:
        await security.login_limit(request, "test@example.com")
    assert error.value.status_code == 429
    fake.eval.side_effect = ConnectionError()
    monkeypatch.setattr(security, "settings", lambda: SimpleNamespace(environment="production"))
    with pytest.raises(HTTPException) as error:
        await security.login_limit(request, "test@example.com")
    assert error.value.status_code == 503

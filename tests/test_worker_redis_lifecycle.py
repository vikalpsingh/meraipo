"""Celery uses a fresh event loop per task; shared Redis must not retain connections."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("task_name", ["daily", "outbox"])
@pytest.mark.parametrize("fails", [False, True])
def test_x_tasks_release_shared_redis_before_loop_closes(monkeypatch, task_name, fails):
    from apps.api import cache
    from apps.worker import x_publishing as worker

    class LoopBoundClient:
        loop = None
        closed = 0

        async def use(self):
            loop = asyncio.get_running_loop()
            assert self.loop is None or self.loop is loop
            self.loop = loop

        async def aclose(self):
            assert not asyncio.get_running_loop().is_closed()
            self.loop = None
            self.closed += 1

    client = LoopBoundClient()
    monkeypatch.setattr(cache, "client", client)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(dispose=AsyncMock()))

    async def tick(*args):
        await client.use()
        if fails:
            raise RuntimeError("source failure")
        return {"status": "COMPLETE"}

    monkeypatch.setattr(worker, "tick", tick)
    for _ in range(2):
        if fails:
            with pytest.raises(RuntimeError, match="source failure"):
                getattr(worker, task_name).run()
        else:
            assert getattr(worker, task_name).run()["status"] == "COMPLETE"
    assert client.closed == 2
    assert client.loop is None

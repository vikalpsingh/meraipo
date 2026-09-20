import os

os.environ["ENVIRONMENT"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./work/test-local.db"
os.environ["PUBLIC_ORIGIN"] = "http://localhost:3000"
os.environ["MARKET_FEEDS_JSON"] = "{}"
os.environ["EXCHANGE_DIRECT_ENABLED"] = "false"
os.environ["EXCHANGE_SOURCES_JSON"] = "[]"
os.environ["MARKET_SCHEDULER_ENABLED"] = "false"
os.environ["CRON_SECRET"] = ""
os.environ["TRADING_CALENDAR_YEAR"] = "0"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api import cache
from apps.api.main import app
from apps.api.security import hasher
from packages.database.models import AdminUser, Base
from packages.database.seed import seed
from packages.database.session import get_session


@pytest.fixture
async def db(tmp_path, monkeypatch):
    url = os.getenv("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    if url.startswith("postgresql") and not url.split("?")[0].endswith("/meraipo_test"):
        raise RuntimeError("Integration tests require an isolated database named meraipo_test")
    engine = create_async_engine(url)
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
        user = AdminUser(
            email="admin@example.com", password_hash=hasher.hash("test-only-password-42")
        )
        session.add(user)
        await session.commit()

        async def dependency():
            yield session

        app.dependency_overrides[get_session] = dependency

        async def invalidation():
            return True

        monkeypatch.setattr(cache, "invalidate", invalidation)
        yield session
    app.dependency_overrides.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        yield client


@pytest.fixture
async def admin_client(client):
    response = await client.post(
        "/api/v1/admin/login",
        json={"email": "admin@example.com", "password": "test-only-password-42"},
        headers={"origin": "http://localhost:3000"},
    )
    assert response.status_code == 200, response.text
    client.headers.update(
        {"origin": "http://localhost:3000", "x-csrf-token": response.json()["csrf_token"]}
    )
    return client

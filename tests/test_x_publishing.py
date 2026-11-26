"""No live X calls: approval, PKCE, identity, budgets, dates, and failure semantics."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from packages.database import models as m
from packages.providers import x_api
from packages.shared import x_publishing as service
from packages.shared.config import settings
from packages.shared.market_config import decrypt_secret, encrypt_secret


def test_schedule_ist_window_and_disabled():
    now = datetime(2026, 11, 18, 8, 45, tzinfo=service.IST)
    assert service.due({"enabled": True, "time": "08:45"}, now)
    assert not service.due({"enabled": True, "time": "09:00"}, now)
    assert not service.due({"enabled": False, "time": "08:45"}, now)
    assert not service.due({"enabled": True, "time": "07:45"}, now)


def test_market_research_rejects_missing_sources_dates_and_length():
    import json

    from packages.providers.market_research import validate_result

    now = datetime(2026, 11, 18, 3, 15, tzinfo=timezone.utc)
    url = "https://www.nseindia.com/market-data"
    result = {
        "ready": True,
        "text": "Markets 18 Nov: prior close snapshot. #StockMarket",
        "facts": [{"claim": "Prior close", "as_of": "2026-11-17T10:00:00Z", "url": url}],
        "reason": "",
    }
    payload = {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "action": {"sources": [{"url": url}]}},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]},
        ],
    }
    text, evidence = validate_result(payload, now)
    assert url not in text and evidence["facts"][0]["url"] == url and evidence["review_required"]
    for bad in ("2026-11-01T10:00:00Z", "2026-11-19T10:00:00Z", "2026-11-17T10:00:00"):
        result["facts"][0]["as_of"] = bad
        payload["output"][1]["content"][0]["text"] = json.dumps(result)
        with pytest.raises(x_api.XError):
            validate_result(payload, now)
    result["facts"][0]["as_of"] = "2026-11-17T10:00:00Z"
    result["facts"][0]["url"] = "https://unapproved.example/fake"
    payload["output"][1]["content"][0]["text"] = json.dumps(result)
    with pytest.raises(x_api.XError):
        validate_result(payload, now)


async def test_opening_image_dedup_and_disabled_publish(db, draft_setup, monkeypatch):
    row, ipo, a = draft_setup
    a.schedules = {"IPO_OPENING": {"enabled": True, "time": "08:45"}}
    await db.commit()
    rows = await service.generate_scheduled(db, "IPO_OPENING")
    assert len(rows) == 1 and rows[0].status == "DRAFT"
    post = rows[0]
    assert post.image_png.startswith(b"\x89PNG")
    more = await service.generate_scheduled(db, "IPO_OPENING")
    assert all(candidate.id != post.id for candidate in more)
    from packages.shared.email_template import content

    mail = await content(
        db,
        ipo.id,
        "https://www.meraipo.com",
        "private-unsubscribe",
        opening=True,
        inline_attachment=True,
    )
    assert mail["chart_png"] == post.image_png
    assert b"private-unsubscribe" not in post.image_png
    post.status, post.approved_at = "APPROVED", m.now()
    a.schedules = {"IPO_OPENING": {"enabled": False, "time": "08:45"}}
    await db.commit()
    with pytest.raises(x_api.XError, match="POST_TYPE_DISABLED"):
        await service.publish(db, post.id)
    a.schedules = {"IPO_OPENING": {"enabled": True, "time": "08:45"}}
    await db.commit()
    request = AsyncMock(side_effect=[{"data": {"id": "888"}}, {"data": {"id": "999"}}])
    monkeypatch.setattr(x_api, "request", request)
    await service.publish(db, post.id)
    assert post.status == "PUBLISHED"
    assert request.call_args_list[1].kwargs["json"]["media"]["media_ids"] == ["888"]


async def test_research_reserved_once_and_never_auto_published(db, draft_setup, monkeypatch):
    from packages.providers import market_research

    _, _, a = draft_setup
    a.schedules = {"MARKET_DAILY": {"enabled": True, "time": "08:45"}}
    a.auto_publish = True
    await db.commit()
    research = AsyncMock(
        return_value=(
            "Markets: prior close.",
            {"facts": [{"claim": "Prior close"}], "generated_at": m.now().isoformat()},
        )
    )
    monkeypatch.setattr(market_research, "generate", research)
    rows = await service.generate_scheduled(db, "MARKET_DAILY")
    assert rows[0].status == "DRAFT"
    assert not await service.generate_scheduled(db, "MARKET_DAILY")
    assert research.await_count == 1
    rows[0].status = "QUEUED"
    await db.commit()
    with pytest.raises(x_api.XError, match="APPROVAL_REQUIRED"):
        await service.publish(db, rows[0].id)


async def test_schedule_admin_validation_and_market_auto_gate(admin_client, db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lock():
        yield

    monkeypatch.setattr(service, "operation_lock", lock)
    r = await admin_client.post(
        "/api/v1/admin/x/schedule", json={"kind": "IPO_OPENING", "enabled": True, "time": "25:00"}
    )
    assert r.status_code == 422
    r = await admin_client.post(
        "/api/v1/admin/x/schedule", json={"kind": "IPO_OPENING", "enabled": True, "time": "09:15"}
    )
    assert r.status_code == 200
    state = (await admin_client.get("/api/v1/admin/x")).json()
    assert state["schedules"]["IPO_OPENING"] == {"enabled": True, "time": "09:15"}
    assert not state["schedules"]["MARKET_DAILY"]["enabled"]
    assert "tokens" not in state and "openai_api_key" not in state
    r = await admin_client.post("/api/v1/admin/x/market-auto", json={"enabled": True})
    assert r.status_code == 409


def test_x_schedule_migration_roundtrip():
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    initial = importlib.import_module("packages.database.migrations.versions.20261117_x_publishing")
    migration = importlib.import_module(
        "packages.database.migrations.versions.20261118_x_schedules"
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE admin_users (id VARCHAR(36) PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(conn)):
            initial.upgrade()
            migration.upgrade()
            assert {c["name"] for c in sa.inspect(conn).get_columns("x_posts")} >= {
                "kind",
                "dedupe_key",
                "image_png",
            }
            assert not any(
                c["column_names"] == ["trading_date"]
                for c in sa.inspect(conn).get_unique_constraints("x_posts")
            )
            migration.downgrade()
            assert any(
                c["column_names"] == ["trading_date"]
                for c in sa.inspect(conn).get_unique_constraints("x_posts")
            )
            initial.downgrade()
    engine.dispose()


def test_length_and_calendar():
    assert service.weighted_length("https://x.co") == 23
    assert service.weighted_length("₹") == 2
    config = SimpleNamespace(trading_calendar_year=2026, trading_holidays="2026-11-17")
    assert not service.trading_day(config, datetime(2026, 11, 17).date())
    assert not service.trading_day(config, datetime(2026, 11, 15).date())
    assert service.trading_day(config, datetime(2026, 11, 18).date())
    with pytest.raises(x_api.XError):
        service.trading_day(config, datetime(2027, 1, 1).date())


@pytest.fixture
async def draft_setup(db, monkeypatch):
    now = datetime(2026, 11, 17, 3, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(m, "now", lambda: now)
    c = settings()
    for k, v in dict(
        x_enabled=True,
        trading_calendar_year=2026,
        trading_holidays="",
        x_daily_attempt_limit=1,
        x_monthly_post_limit=20,
    ).items():
        monkeypatch.setattr(c, k, v)
    ipo = await db.scalar(select(m.IPO))
    company = await db.get(m.Company, ipo.company_id)
    company.is_demo = False
    ipo.status = "OPEN"
    ipo.raw_status = None
    ipo.source_timestamp = now - timedelta(hours=1)
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    dates.open_date = now.date()
    dates.close_date = now.date() + timedelta(days=2)
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    guide.verification_status = "VERIFIED"
    guide.schedule_status = "CONFIRMED"
    guide.reviewed_on = now.date()
    guide.source_url = "https://www.nseindia.com/ipo"
    await db.commit()
    row = await service.generate(db)
    a = await service.account(db)
    a.user_id = "123"
    a.tokens = encrypt_secret("{}")
    await db.commit()
    monkeypatch.setattr(x_api, "access_token", AsyncMock(return_value="private"))
    monkeypatch.setattr(
        x_api, "identity", AsyncMock(return_value={"id": "123", "username": "MeraIPO"})
    )
    return row, ipo, a


async def test_approval_required_and_duplicate_publish(db, draft_setup, monkeypatch):
    row, ipo, a = draft_setup
    send = AsyncMock(return_value={"data": {"id": "987"}})
    monkeypatch.setattr(x_api, "request", send)
    assert row.status == "DRAFT" and service.weighted_length(row.content) <= 280
    with pytest.raises(x_api.XError, match="APPROVAL_REQUIRED"):
        await service.publish(db, row.id)
    assert not send.called
    row.status = "APPROVED"
    row.approved_at = m.now()
    await db.commit()
    await service.publish(db, row.id)
    assert row.status == "PUBLISHED" and row.post_id == "987"
    with pytest.raises(x_api.XError):
        await service.publish(db, row.id)
    assert send.await_count == 1


async def test_ambiguous_send_is_not_retried(db, draft_setup, monkeypatch):
    row, _, _ = draft_setup
    row.status = "APPROVED"
    row.approved_at = m.now()
    await db.commit()
    monkeypatch.setattr(
        x_api, "request", AsyncMock(side_effect=x_api.XError("NETWORK_OUTCOME_UNKNOWN"))
    )
    await service.publish(db, row.id)
    assert row.status == "UNCERTAIN" and row.attempts == 1
    with pytest.raises(x_api.XError):
        await service.publish(db, row.id)


async def test_stale_data_and_budget_block_before_api(db, draft_setup, monkeypatch):
    row, ipo, _ = draft_setup
    row.status = "APPROVED"
    row.approved_at = m.now()
    ipo.source_timestamp = m.now() - timedelta(days=10)
    await db.commit()
    with pytest.raises(x_api.XError, match="NO_FRESH"):
        await service.publish(db, row.id)
    ipo.source_timestamp = m.now()
    row.attempts = 1
    await db.commit()
    with pytest.raises(x_api.XError, match="DAILY_ATTEMPT_LIMIT"):
        await service.publish(db, row.id)


async def test_wrong_account_rejected(monkeypatch):
    monkeypatch.setattr(
        x_api, "request", AsyncMock(return_value={"data": {"id": "123", "username": "Wrong"}})
    )
    with pytest.raises(x_api.XError, match="WRONG_X_ACCOUNT"):
        await x_api.identity("secret")


async def test_refresh_persists_rotated_tokens(db, monkeypatch):
    a = await service.account(db)
    a.tokens = encrypt_secret('{"access_token":"old","refresh_token":"old-refresh"}')
    a.expires_at = m.now() - timedelta(minutes=1)
    await db.commit()
    monkeypatch.setattr(
        x_api,
        "exchange",
        AsyncMock(
            return_value={
                "access_token": "new",
                "refresh_token": "new-refresh",
                "scope": x_api.SCOPES,
                "expires_in": 7200,
            }
        ),
    )
    assert await x_api.access_token(db, a) == "new"
    assert "new-refresh" in decrypt_secret(a.tokens)
    assert "new-refresh" not in a.tokens


async def test_admin_only_and_csrf(client, admin_client):
    # admin_client fixture signs in the same client; remove cookie for public check.
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert (await client.get("/api/v1/admin/x")).status_code == 401
    client.cookies.update(cookies)
    headers = dict(client.headers)
    client.headers.pop("x-csrf-token", None)
    assert (await client.post("/api/v1/admin/x/draft")).status_code == 403
    client.headers.update(headers)


async def test_pkce_bound_single_use_flow(db, monkeypatch):
    import base64
    import hashlib
    import json
    from urllib.parse import parse_qs, urlsplit

    from fastapi import HTTPException

    from apps.api import x_routes

    config = settings()
    monkeypatch.setattr(config, "x_enabled", True)
    monkeypatch.setattr(config, "x_client_id", "client")
    monkeypatch.setattr(config, "x_client_secret", SecretStr("client-secret"))
    monkeypatch.setattr(
        config, "config_encryption_key", SecretStr("test-config-encryption-key-at-least-32")
    )
    monkeypatch.setattr(config, "public_origin", "https://www.meraipo.com")
    monkeypatch.setattr(config, "x_redirect_uri", "https://www.meraipo.com/api/v1/admin/x/callback")
    store = {}

    async def put(key, value, **kwargs):
        store[key] = value

    async def take(key):
        return store.pop(key, None)

    monkeypatch.setattr(x_routes.client, "set", put)
    monkeypatch.setattr(x_routes.client, "getdel", take)
    auth = (SimpleNamespace(id=None), SimpleNamespace(id="session1"))
    result = await x_routes.connect(auth, db)
    params = parse_qs(urlsplit(result["url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    flow = json.loads(decrypt_secret(store["x:oauth:session1"]))
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest())
        .decode()
        .rstrip("=")
    ]
    assert flow["verifier"] not in result["url"]
    with pytest.raises(HTTPException):
        await x_routes.callback(state="wrong", code="private-code", error="", auth=auth, db=db)
    assert not store
    with pytest.raises(HTTPException):
        await x_routes.callback(
            state=flow["state"], code="private-code", error="", auth=auth, db=db
        )


async def test_auto_requires_success(db, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import HTTPException

    @asynccontextmanager
    async def unlocked():
        yield

    monkeypatch.setattr(service, "operation_lock", unlocked)
    from apps.api.x_routes import AutoInput, auto

    with pytest.raises(HTTPException):
        await auto(AutoInput(enabled=True), (SimpleNamespace(id=None),), db)


def test_blocked_market_retains_review_only_explanation():
    import json

    from packages.providers.market_research import validate_result

    payload = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "ready": False,
                                "text": "Unverified candidate",
                                "facts": [],
                                "reason": "No dated exchange evidence",
                            }
                        ),
                    }
                ],
            }
        ],
    }
    text, evidence = validate_result(payload, datetime.now(timezone.utc))
    assert text == "SKIP_POST"
    assert evidence["reason"] == "No dated exchange evidence"
    assert evidence["review_only"] is True


async def test_review_includes_ipo_with_unverified_guide(db, draft_setup):
    from apps.api.x_routes import GenerateInput, review_sources

    row, ipo, account = draft_setup
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    guide.verification_status = "UNVERIFIED"
    await db.commit()
    result = await review_sources(GenerateInput(kind="IPO_OPENING"), auth=None, db=db)
    assert result["review"]["items"]
    assert "Guide verified" not in result["review"]["items"][0]["checks"]
    assert result["review"]["items"][0]["checks"]["Public feed source"] is True


async def test_manual_generation_requires_review_even_with_auto(db, draft_setup):
    row, ipo, account = draft_setup
    account.auto_publish = True
    account.schedules = {"IPO_OPENING": {"enabled": True, "time": "08:45"}}
    await db.commit()
    rows = await service.generate_scheduled(db, "IPO_OPENING", manual=True)
    assert rows[0].status == "DRAFT"


async def test_manual_draft_dedup_validation_and_approval(admin_client, db, monkeypatch):
    from contextlib import asynccontextmanager

    from apps.api import x_routes

    @asynccontextmanager
    async def lock():
        yield

    monkeypatch.setattr(service, "operation_lock", lock)
    monkeypatch.setattr(x_routes, "configured", lambda: settings())
    for text in ("   ", "a" * 281):
        response = await admin_client.post("/api/v1/admin/x/manual-draft", json={"content": text})
        assert response.status_code == 422
    for _ in range(2):
        response = await admin_client.post(
            "/api/v1/admin/x/manual-draft", json={"content": "MeraIPO connection test."}
        )
        assert response.status_code == 200
    rows = (await db.scalars(select(m.XPost).where(m.XPost.kind == "MANUAL"))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "DRAFT" and row.attempts == 0 and row.approved_at is None
    assert (await admin_client.post(f"/api/v1/admin/x/{row.id}/publish")).status_code == 409
    monkeypatch.setattr(
        service,
        "snapshot",
        AsyncMock(side_effect=AssertionError("manual text must not query IPO content")),
    )
    assert (await admin_client.post(f"/api/v1/admin/x/{row.id}/approve")).status_code == 200
    assert (await admin_client.post(f"/api/v1/admin/x/{row.id}/publish")).status_code == 200
    await db.refresh(row)
    assert row.status == "QUEUED"


async def test_public_feed_opening_closing_without_manual_guide(db, draft_setup):
    row, ipo, a = draft_setup
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    await db.delete(guide)
    ipo.source_provider = "IPOALERTS"
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    dates.close_date = dates.open_date
    a.auto_publish = True
    a.schedules = {
        kind: {"enabled": True, "time": "08:45"} for kind in ("IPO_OPENING", "IPO_CLOSING")
    }
    await db.commit()
    opening = (await service.generate_scheduled(db, "IPO_OPENING"))[0]
    closing = (await service.generate_scheduled(db, "IPO_CLOSING"))[0]
    assert opening.status == closing.status == "QUEUED"
    assert "opens today" in opening.content and "closes today" in closing.content
    assert opening.dedupe_key != closing.dedupe_key
    assert closing.image_png and opening.image_png != closing.image_png
    await service.validate_post(db, closing)
    assert not await service.generate_scheduled(db, "IPO_CLOSING")
    ipo.source_timestamp = m.now() - timedelta(days=3)
    await db.commit()
    with pytest.raises(x_api.XError, match="IPO_PUBLIC_SOURCE_NOT_READY"):
        await service.validate_post(db, closing)


async def test_ipo_blocked_feed_refresh_recovery(db, draft_setup):
    row, ipo, a = draft_setup
    a.auto_publish = True
    a.schedules = {"IPO_OPENING": {"enabled": True, "time": "08:45"}}
    ipo.source_timestamp = m.now() - timedelta(days=3)
    await db.commit()
    blocked = (await service.generate_scheduled(db, "IPO_OPENING"))[0]
    assert blocked.status == "BLOCKED"
    assert not await service.generate_scheduled(db, "IPO_OPENING")
    ipo.source_timestamp = m.now()
    await db.commit()
    recovered = (await service.generate_scheduled(db, "IPO_OPENING"))[0]
    assert recovered.id == blocked.id and recovered.status == "QUEUED"
    ipo.quality = "CONFLICT"
    await db.commit()
    with pytest.raises(x_api.XError, match="IPO_PUBLIC_SOURCE_NOT_READY"):
        await service.validate_post(db, recovered)


async def test_openai_connection_control_and_cooldown(admin_client, monkeypatch):
    from apps.api import x_routes
    from packages.providers import market_research

    monkeypatch.setattr(settings(), "openai_api_key", SecretStr("test-private"))
    limiter = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(x_routes.client, "set", limiter)
    generate = AsyncMock(
        return_value={
            "text": "MeraIPO integration test, not a market update.",
            "model": "test-model",
            "elapsed_ms": 20,
        }
    )
    monkeypatch.setattr(market_research, "connection_test", generate)
    result = await admin_client.post("/api/v1/admin/x/openai-test")
    assert result.status_code == 200
    assert result.json()["openai_test"]["text"].startswith("MeraIPO")
    assert "test-private" not in result.text
    assert (await admin_client.post("/api/v1/admin/x/openai-test")).status_code == 429
    assert generate.await_count == 1
    assert limiter.call_args.kwargs == {"nx": True, "ex": 300}


async def test_openai_connection_provider_no_research(monkeypatch):
    import httpx

    from packages.providers import market_research

    monkeypatch.setattr(settings(), "openai_api_key", SecretStr("test-private"))
    response = httpx.Response(
        200,
        json={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Integration test."}],
                }
            ],
        },
    )
    post = AsyncMock(return_value=response)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    client = Client()
    client.post = post
    monkeypatch.setattr(market_research.httpx, "AsyncClient", lambda **kwargs: client)
    result = await market_research.connection_test()
    assert result["text"] == "Integration test."
    body = post.call_args.kwargs["json"]
    assert "tools" not in body and body["store"] is False
    post.return_value = httpx.Response(401)
    with pytest.raises(x_api.XError, match="OPENAI_HTTP_401"):
        await market_research.connection_test()


@pytest.mark.parametrize(
    "provider_code,expected",
    [
        ("insufficient_quota", "OPENAI_QUOTA_EXHAUSTED"),
        ("rate_limit_exceeded", "OPENAI_RATE_LIMITED"),
        ("unknown", "OPENAI_HTTP_429"),
    ],
)
def test_openai_429_classification(provider_code, expected):
    import httpx

    from packages.providers.market_research import response_error

    error = response_error(
        httpx.Response(
            429, json={"error": {"code": provider_code, "message": "private account data"}}
        )
    )
    assert error.code == expected and error.status == 429
    assert "private" not in str(error)


async def test_current_ipo_test_disabled_schedule_and_dedup(db, draft_setup):
    _, ipo, account = draft_setup
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    dates.open_date = m.now().date() - timedelta(days=1)
    account.auto_publish = True
    account.schedules = {}
    await db.commit()
    row = await service.generate_test(db, "IPO_OPENING", ipo.id)
    assert row.status == "DRAFT" and row.kind == "IPO_TEST"
    assert "open for subscription" in row.content and "opens today" not in row.content
    assert row.image_png.startswith(b"\x89PNG")
    assert (await service.generate_test(db, "IPO_OPENING", ipo.id)).id == row.id
    await service.validate_post(db, row)
    row.status = "QUEUED"
    await db.commit()
    with pytest.raises(x_api.XError, match="APPROVAL_REQUIRED"):
        await service.publish(db, row.id)


async def test_market_test_has_separate_budget_and_never_autopublishes(
    db, draft_setup, monkeypatch
):
    from packages.providers import market_research

    _, _, account = draft_setup
    account.auto_publish = True
    await db.commit()
    research = AsyncMock(
        return_value=(
            "Prior close summary #StockMarket",
            {"facts": [{"claim": "Prior close"}], "generated_at": m.now().isoformat()},
        )
    )
    monkeypatch.setattr(market_research, "generate", research)
    row = await service.generate_test(db, "MARKET_DAILY")
    assert row.kind == "MARKET_TEST" and row.status == "DRAFT"
    assert (await service.generate_test(db, "MARKET_DAILY")).id == row.id
    assert research.await_count == 1
    await service.validate_post(db, row)


async def test_market_weekend_skip_without_api(monkeypatch):
    from packages.providers import market_research

    monkeypatch.setattr(settings(), "openai_api_key", SecretStr("test"))
    text, evidence = await market_research.generate(
        datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
    )
    assert text == "SKIP_POST" and evidence["reason"] == "Weekend"


async def test_market_holiday_and_closing_prompt_context(monkeypatch):
    import httpx

    from packages.providers import market_research

    config = settings()
    monkeypatch.setattr(config, "openai_api_key", SecretStr("test"))
    monkeypatch.setattr(config, "trading_calendar_year", 2026)
    monkeypatch.setattr(config, "trading_holidays", "2026-11-24")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    client = Client()
    client.post = AsyncMock(return_value=httpx.Response(200, json={}))
    monkeypatch.setattr(market_research.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(market_research, "validate_result", lambda payload, now: ("SKIP_POST", {}))
    await market_research.generate(datetime(2026, 11, 24, 3, 15, tzinfo=timezone.utc))
    body = client.post.call_args.kwargs["json"]
    assert "Phase: holiday" in body["input"] and "+05:30" in body["input"]
    assert "No individual company names, URLs, citations" in body["instructions"]
    await market_research.generate(datetime(2026, 11, 25, 10, 30, tzinfo=timezone.utc))
    assert "Phase: closing" in client.post.call_args.kwargs["json"]["input"]


@pytest.mark.parametrize(
    "text",
    [
        "Market #StockMarket https://example.com",
        "Market #StockMarket #Nifty",
        "Market update",
        "**Market** #StockMarket",
        "📊" * 140 + " #StockMarket",
    ],
)
def test_market_public_format_rejects_links_hashtags_markdown_and_length(text):
    import json

    from packages.providers.market_research import validate_result

    url = "https://www.nseindia.com/market-data"
    now = datetime(2026, 11, 25, 3, 15, tzinfo=timezone.utc)
    body = {
        "ready": True,
        "text": text,
        "reason": "",
        "facts": [{"claim": "Prior close", "as_of": "2026-11-23T10:00:00Z", "url": url}],
    }
    payload = {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "action": {"sources": [{"url": url}]}},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(body)}]},
        ],
    }
    with pytest.raises(x_api.XError):
        validate_result(payload, now)


async def test_content_test_api_selected_ipo_and_skip_not_publishable(
    admin_client, db, draft_setup, monkeypatch
):
    from contextlib import asynccontextmanager

    from apps.api import x_routes
    from packages.providers import market_research

    _, ipo, _ = draft_setup

    @asynccontextmanager
    async def lock():
        yield

    monkeypatch.setattr(service, "operation_lock", lock)
    monkeypatch.setattr(x_routes, "configured", lambda: settings())
    response = await admin_client.post(
        "/api/v1/admin/x/content-test", json={"kind": "IPO_OPENING", "ipo_id": ipo.id}
    )
    assert response.status_code == 200
    row = await db.get(m.XPost, response.json()["test_id"])
    assert row.kind == "IPO_TEST" and row.evidence["ipo_id"] == ipo.id
    monkeypatch.setattr(settings(), "openai_api_key", SecretStr("test"))
    monkeypatch.setattr(
        market_research,
        "generate",
        AsyncMock(return_value=("SKIP_POST", {"reason": "No reliable core data", "facts": []})),
    )
    response = await admin_client.post(
        "/api/v1/admin/x/content-test", json={"kind": "MARKET_DAILY"}
    )
    key = response.json()["test_id"]
    assert (await db.get(m.XPost, key)).status == "SKIPPED"
    assert (await admin_client.post(f"/api/v1/admin/x/{key}/approve")).status_code == 409
    assert (await admin_client.post(f"/api/v1/admin/x/{key}/publish")).status_code == 409


@pytest.mark.parametrize("prior_status", ["PUBLISHED", "UNCERTAIN", "SENDING"])
async def test_cross_flow_duplicate_content_not_sent(db, draft_setup, monkeypatch, prior_status):
    from packages.providers import market_research

    prior, _, _ = draft_setup
    prior.status = prior_status
    await db.commit()
    research = AsyncMock(
        return_value=(
            prior.content,
            {"facts": [{"claim": "prior"}], "generated_at": m.now().isoformat()},
        )
    )
    monkeypatch.setattr(market_research, "generate", research)
    row = await service.generate_test(db, "MARKET_DAILY")
    assert row.status == "BLOCKED"
    assert row.error_code == "DUPLICATE_CONTENT_REVIEW_EXISTING_POST"
    assert row.evidence["duplicate_post_id"] == prior.id
    assert row.attempts == 0


async def test_market_skip_repeats_on_another_day_without_hash_conflict(
    db, draft_setup, monkeypatch
):
    from packages.providers import market_research

    now = m.now()
    monkeypatch.setattr(
        market_research,
        "generate",
        AsyncMock(return_value=("SKIP_POST", {"reason": "No data", "facts": []})),
    )
    first = await service.generate_test(db, "MARKET_DAILY")
    monkeypatch.setattr(m, "now", lambda: now + timedelta(days=1))
    second = await service.generate_test(db, "MARKET_DAILY")
    assert first.id != second.id and first.status == second.status == "SKIPPED"
    assert first.content_hash is None and second.content_hash is None


async def test_successful_approved_market_test_unlocks_opt_in(
    admin_client, db, draft_setup, monkeypatch
):
    from contextlib import asynccontextmanager

    from apps.api import x_routes

    @asynccontextmanager
    async def lock():
        yield

    monkeypatch.setattr(service, "operation_lock", lock)
    monkeypatch.setattr(x_routes, "configured", lambda: settings())
    row, _, _ = draft_setup
    row.kind = "MARKET_TEST"
    row.status = "PUBLISHED"
    row.approved_at = m.now()
    await db.commit()
    response = await admin_client.post("/api/v1/admin/x/market-auto", json={"enabled": True})
    assert response.status_code == 200
    assert service.schedules(await service.account(db))["MARKET_DAILY"]["auto_publish"] is True

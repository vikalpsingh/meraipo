from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from apps.api.ad_images import CachedLogo
from apps.api.security import verify
from packages.database.models import (
    AdminSession,
    AdminUser,
    Audit,
    MarketConfiguration,
    Quarterly,
)
from packages.shared.market_config import load_market_settings


async def test_catalog_from_database_and_missing_values(client):
    opened = (await client.get("/api/v1/ipos/open")).json()["items"]
    assert len(opened) == 3
    assert all(c["open_date"] <= date.today().isoformat() <= c["close_date"] for c in opened)
    upcoming = (await client.get("/api/v1/ipos/upcoming")).json()["items"]
    assert len(upcoming) == 3
    missing = next(c for c in upcoming if c["slug"] == "cedar-foods")
    assert missing["gmp"] is None and missing["price_high"] is None


async def test_tracker_one_row_filters_and_pagination(client):
    result = (await client.get("/api/v1/tracker?page_size=100")).json()
    assert result["total"] == 10
    assert len({c["id"] for c in result["items"]}) == 10
    c = result["items"][0]
    filtered = (
        await client.get(
            f"/api/v1/tracker?fy={c['listing_fy']}&quarter={c['listing_quarter']}&board={c['board']}"
        )
    ).json()
    assert all(
        x["listing_fy"] == c["listing_fy"]
        and x["listing_quarter"] == c["listing_quarter"]
        and x["board"] == c["board"]
        for x in filtered["items"]
    )
    assert len((await client.get("/api/v1/tracker?page_size=2&page=2")).json()["items"]) == 2
    assert (await client.get("/api/v1/tracker?page_size=101")).status_code == 422
    assert (await client.get("/api/v1/tracker?quarter=7")).status_code == 422


async def test_company_baseline_history_and_not_found(client):
    c = (await client.get("/api/v1/companies/prava-technologies/journey")).json()
    assert len(c["quarters"]) == 6
    assert c["baseline"]["revenue"] == 460
    assert c["quarters"][-1]["revenue_yoy"] is not None
    assert c["quarters"][0]["revenue_yoy"] is None
    assert (await client.get("/api/v1/companies/nonexistent")).status_code == 404


@pytest.mark.parametrize("path", ["dashboard", "messages", "advertisements", "audit", "session"])
async def test_admin_reads_require_auth(client, path):
    assert (await client.get("/api/v1/admin/" + path)).status_code == 401


async def test_password_hash_and_login_errors(client, db):
    user = await db.scalar(select(AdminUser))
    assert user.password_hash.startswith("$argon2id$")
    assert verify("test-only-password-42", user.password_hash)
    response = await client.post(
        "/api/v1/admin/login",
        json={"email": "admin@example.com", "password": "wrong"},
        headers={"origin": "http://localhost:3000"},
    )
    assert response.status_code == 401
    assert "wrong" not in response.text
    assert (
        await client.post(
            "/api/v1/admin/login",
            json={"email": "admin@example.com", "password": "test-only-password-42"},
        )
    ).status_code == 403


async def test_csrf_and_origin_rejected(admin_client):
    data = {"title": "Thought", "content": "Research patiently."}
    assert (
        await admin_client.post(
            "/api/v1/admin/messages", json=data, headers={"x-csrf-token": "wrong"}
        )
    ).status_code == 403
    assert (
        await admin_client.post(
            "/api/v1/admin/messages", json=data, headers={"origin": "https://attacker.test"}
        )
    ).status_code == 403


async def test_message_publish_disable_schedule_and_audit(admin_client, db):
    data = {
        "title": "A patient perspective",
        "content": "Study the business before the price.",
        "attribution": "MeraIPO editorial",
    }
    created = await admin_client.post("/api/v1/admin/messages", json=data)
    assert created.status_code == 201, created.text
    assert (await admin_client.get("/api/v1/site/message")).json()["message"]["content"] == data[
        "content"
    ]
    ident = created.json()["id"]
    assert (
        await admin_client.put("/api/v1/admin/messages/" + ident, json={**data, "enabled": False})
    ).status_code == 200
    assert (await admin_client.get("/api/v1/site/message")).json()["message"]["id"] != ident
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    await admin_client.put("/api/v1/admin/messages/" + ident, json={**data, "active_from": future})
    assert (await admin_client.get("/api/v1/site/message")).json()["message"]["id"] != ident
    assert (
        await db.scalar(
            select(func.count()).select_from(Audit).where(Audit.action == "message.update")
        )
    ) == 2


async def test_quarter_revision_preserves_baseline_and_duplicate(admin_client, db):
    data = {
        "financial_year": 2026,
        "quarter": 2,
        "revenue": 999,
        "pat": 80,
        "source_url": "https://example.com/filing",
        "import_key": "new-result-key-123",
    }
    first = await admin_client.post(
        "/api/v1/admin/companies/prava-technologies/quarters", json=data
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 2
    second = await admin_client.post(
        "/api/v1/admin/companies/prava-technologies/quarters", json=data
    )
    assert second.json()["created"] is False
    journey = (await admin_client.get("/api/v1/companies/prava-technologies")).json()
    assert journey["baseline"]["revenue"] == 460
    assert journey["quarters"][-1]["revenue"] == 999
    assert (await db.scalar(select(func.count()).select_from(Quarterly))) == 37


async def test_gmp_history_and_nullable_value(admin_client):
    data = {
        "value": None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://example.com/gmp",
        "import_key": "gmp-test-null-123",
    }
    assert (
        await admin_client.post("/api/v1/admin/ipos/aarya-energy/gmp", json=data)
    ).status_code == 200
    c = (await admin_client.get("/api/v1/companies/aarya-energy")).json()
    assert c["gmp"] is None and len(c["gmp_history"]) == 4


async def test_ad_disabled_by_default_and_https_validation(admin_client):
    assert (await admin_client.get("/api/v1/site/advertisements")).json()["items"] == []
    data = {"text": "Research tools", "destination_url": "https://example.com", "enabled": False}
    response = await admin_client.post("/api/v1/admin/advertisements", json=data)
    assert response.status_code == 201
    assert (await admin_client.get("/api/v1/site/advertisements")).json()["items"] == []
    await admin_client.put(
        "/api/v1/admin/advertisements/" + response.json()["id"], json={**data, "enabled": True}
    )
    assert len((await admin_client.get("/api/v1/site/advertisements")).json()["items"]) == 1
    assert (
        await admin_client.post(
            "/api/v1/admin/advertisements", json={**data, "destination_url": "javascript:alert(1)"}
        )
    ).status_code == 422


async def test_ad_logo_is_downloaded_once_and_served_locally(admin_client, monkeypatch):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return CachedLogo(svg, "image/svg+xml", "a" * 64)

    monkeypatch.setattr("apps.api.main.fetch_logo", fake_fetch)
    data = {
        "text": "Trade with Kite",
        "image_url": "https://commons.wikimedia.org/wiki/File:Zerodha_Kite_logo.svg",
        "destination_url": "https://kite.zerodha.com",
        "enabled": True,
    }
    created = await admin_client.post("/api/v1/admin/advertisements", json=data)
    assert created.status_code == 201, created.text
    assert created.json()["image_cached"] is True
    assert created.json()["image_bytes"] == len(svg)
    assert created.json()["image_url"] == data["image_url"]

    public = (await admin_client.get("/api/v1/site/advertisements")).json()["items"][0]
    assert public["image_url"].startswith(
        f"/api/v1/site/advertisements/{created.json()['id']}/image?v="
    )
    image = await admin_client.get(public["image_url"])
    assert image.content == svg
    assert image.headers["content-type"] == "image/svg+xml"
    assert image.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (
        await admin_client.get(
            public["image_url"], headers={"if-none-match": image.headers["etag"]}
        )
    ).status_code == 304

    updated = await admin_client.put(
        "/api/v1/admin/advertisements/" + created.json()["id"], json=data
    )
    assert updated.status_code == 200
    assert calls == [data["image_url"]]


async def test_market_configuration_is_encrypted_and_loaded_for_new_jobs(admin_client, db):
    current = await admin_client.get("/api/v1/admin/market/config")
    assert current.status_code == 200
    assert current.json()["source"] == "environment"
    assert "ipoalerts_api_key" not in current.json()
    payload = {
        "provider_mode": "market-feeds",
        "market_scheduler_enabled": True,
        "market_scheduler_driver": "celery",
        "exchange_direct_enabled": True,
        "nse_subscription_categories_enabled": True,
        "ipo_data_provider": "ipoalerts",
        "ipoalerts_api_key": "provider-secret-value",
        "clear_ipoalerts_api_key": False,
        "ipoalerts_page_size": 50,
        "market_feeds_json": '{"gmp":{"licensed":{"url":"https://example.com/feed","token":"feed-secret","enabled":true,"authority":"UNOFFICIAL"}}}',
        "exchange_sources_json": "[]",
        "bse_ipo_issues_json": "[]",
        "trading_holidays": "2026-10-02,2026-11-08",
        "trading_calendar_year": 2026,
    }
    saved = await admin_client.put("/api/v1/admin/market/config", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "admin"
    assert saved.json()["ipoalerts_api_key_configured"] is True
    assert "ipoalerts_api_key" not in saved.json()
    row = await db.get(MarketConfiguration, "market")
    assert "provider-secret-value" not in row.ipoalerts_api_key_encrypted
    effective = await load_market_settings(db)
    assert effective.provider_mode == "market-feeds"
    assert effective.market_scheduler_enabled is True
    assert effective.ipoalerts_api_key.get_secret_value() == "provider-secret-value"
    assert "feed-secret" not in row.market_feeds_json_encrypted
    assert "********" in saved.json()["market_feeds_json"]
    assert "feed-secret" in effective.market_feeds_json
    assert (await admin_client.get("/api/v1/admin/dashboard")).json()["provider_mode"] == (
        "market-feeds"
    )

    payload["ipoalerts_api_key"] = None
    payload["ipoalerts_page_size"] = 25
    payload["market_feeds_json"] = saved.json()["market_feeds_json"]
    updated = await admin_client.put("/api/v1/admin/market/config", json=payload)
    assert updated.status_code == 200
    assert (await load_market_settings(db)).ipoalerts_api_key.get_secret_value() == (
        "provider-secret-value"
    )
    assert "feed-secret" in (await load_market_settings(db)).market_feeds_json


async def test_market_configuration_rejects_invalid_provider_json(admin_client):
    current = (await admin_client.get("/api/v1/admin/market/config")).json()
    payload = {
        key: value
        for key, value in current.items()
        if key
        not in {
            "ipoalerts_api_key_configured",
            "source",
            "updated_at",
        }
    }
    payload.update(
        ipoalerts_api_key=None,
        clear_ipoalerts_api_key=False,
        market_feeds_json="not-json",
    )
    assert (await admin_client.put("/api/v1/admin/market/config", json=payload)).status_code == 422


async def test_logout_revokes_session(admin_client, db):
    assert (await admin_client.post("/api/v1/admin/logout", json={})).status_code == 200
    assert (await admin_client.get("/api/v1/admin/dashboard")).status_code == 401
    assert (await db.scalar(select(func.count()).select_from(AdminSession))) == 0


async def test_security_headers_and_error_model(client):
    response = await client.get("/api/v1/tracker?quarter=0")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    assert response.json()["error"]["code"] == "validation_error"


async def test_ipo_create_edit_and_immutable_baseline(admin_client):
    data = {
        "name": "Test Company",
        "slug": "test-company",
        "sector": "Services",
        "status": "UPCOMING",
        "price_high": 100,
        "source_url": "https://example.com/rhp",
        "baseline": {"revenue": 50},
    }
    assert (await admin_client.post("/api/v1/admin/ipos", json=data)).status_code == 201
    assert (await admin_client.put("/api/v1/admin/ipos/test-company", json=data)).status_code == 409
    data.pop("baseline")
    data["price_high"] = 120
    assert (await admin_client.put("/api/v1/admin/ipos/test-company", json=data)).status_code == 200
    result = (await admin_client.get("/api/v1/ipos/test-company")).json()
    assert result["price_high"] == 120 and result["baseline"]["revenue"] == 50


async def test_import_validation_and_idempotency_payload_conflict(admin_client, db):
    row = {
        "financial_year": 2027,
        "quarter": 1,
        "revenue": 111,
        "source_url": "https://example.com/results",
        "import_key": "batch-quarter-unique-1",
    }
    path = "/api/v1/admin/companies/prava-technologies/quarters/import"
    assert (await admin_client.post(path, json=[row, {**row, "quarter": 5}])).status_code == 422
    assert (await db.scalar(select(func.count()).select_from(Quarterly))) == 36
    assert (await admin_client.post(path, json=[row])).status_code == 200
    duplicate = (await admin_client.post(path, json=[row])).json()
    assert duplicate["items"][0]["created"] is False
    assert (await admin_client.post(path, json=[{**row, "revenue": 222}])).status_code == 409


async def test_expired_session_rejected(admin_client, db):
    session = await db.scalar(select(AdminSession))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert (await admin_client.get("/api/v1/admin/dashboard")).status_code == 401


async def test_request_body_limit(client):
    assert (await client.post("/api/v1/admin/login", content=b"x" * 1_048_577)).status_code == 413

    async def chunks():
        yield b"x" * 600_000
        yield b"x" * 600_000

    assert (await client.post("/api/v1/admin/login", content=chunks())).status_code == 413

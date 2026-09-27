from sqlalchemy import delete, select

from apps.api.feature_routes import FEATURES
from packages.database.models import Audit, FeatureFlag


async def test_flags_default_hidden(client, db, monkeypatch):
    await db.execute(delete(FeatureFlag))
    await db.commit()
    monkeypatch.setitem(FEATURES, "future_tab", {"label": "Future", "description": "Future"})
    response = await client.get("/api/v1/site/features")
    assert response.json()["features"] == {"ipo_tracker": False, "future_tab": False}
    assert (await client.get("/api/v1/tracker")).status_code == 404


async def test_admin_release_and_hide(admin_client, db):
    for enabled in (False, True, False):
        response = await admin_client.put(
            "/api/v1/admin/features/ipo_tracker", json={"enabled": enabled}
        )
        assert response.status_code == 200, response.text
        assert (await db.get(FeatureFlag, "ipo_tracker")).enabled is enabled
        assert (await admin_client.get("/api/v1/site/features")).json()["features"][
            "ipo_tracker"
        ] is enabled
        assert (await admin_client.get("/api/v1/tracker")).status_code == (200 if enabled else 404)
    events = (await db.scalars(select(Audit).where(Audit.action == "feature.update"))).all()
    assert len(events) == 3
    assert events[-1].changes == {"key": "ipo_tracker", "before": True, "enabled": False}
    assert (await admin_client.get("/api/v1/admin/features")).json()["items"][0]["enabled"] is False


async def test_flags_require_auth(client):
    assert (await client.get("/api/v1/admin/features")).status_code == 401
    assert (
        await client.put("/api/v1/admin/features/ipo_tracker", json={"enabled": True})
    ).status_code == 401


async def test_flags_validate_and_require_csrf(admin_client):
    assert (
        await admin_client.put("/api/v1/admin/features/unknown", json={"enabled": True})
    ).status_code == 404
    assert (
        await admin_client.put("/api/v1/admin/features/ipo_tracker", json={"enabled": "true"})
    ).status_code == 422
    admin_client.headers.pop("x-csrf-token")
    assert (
        await admin_client.put("/api/v1/admin/features/ipo_tracker", json={"enabled": True})
    ).status_code == 403

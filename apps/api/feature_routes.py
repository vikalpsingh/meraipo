"""Register public features here; every new feature starts hidden until enabled."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool
from sqlalchemy import select

from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session

FEATURES = {
    "ipo_tracker": {
        "label": "IPO Tracker",
        "description": "Show IPO Tracker navigation and allow access to its page and API.",
    },
}
router = APIRouter()


async def flags(db):
    stored = {row.key: row.enabled for row in (await db.scalars(select(m.FeatureFlag))).all()}
    return {key: stored.get(key, False) for key in FEATURES}


def require_feature(key):
    async def check(db=Depends(get_session)):
        if not (await flags(db)).get(key, False):
            raise HTTPException(404, "Feature not available")

    return check


@router.get("/api/v1/site/features")
async def public_features(db=Depends(get_session)):
    return {"features": await flags(db)}


@router.get("/api/v1/admin/features")
async def list_features(auth=Depends(admin), db=Depends(get_session)):
    values = await flags(db)
    return {
        "items": [{"key": key, **info, "enabled": values[key]} for key, info in FEATURES.items()]
    }


class FeatureUpdate(BaseModel):
    enabled: StrictBool


@router.put("/api/v1/admin/features/{key}")
async def update_feature(
    key: str, data: FeatureUpdate, auth=Depends(admin), db=Depends(get_session)
):
    if key not in FEATURES:
        raise HTTPException(404, "Unknown feature")
    row = await db.get(m.FeatureFlag, key)
    before = row.enabled if row else False
    if row is None:
        row = m.FeatureFlag(key=key)
        db.add(row)
    row.enabled = data.enabled
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="feature.update",
            changes={"key": key, "before": before, "enabled": data.enabled},
        )
    )
    await db.commit()
    return {"key": key, "enabled": row.enabled}

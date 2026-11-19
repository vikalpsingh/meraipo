"""Administrator-only X connection and approval workflow."""

import base64
import hashlib
import json
import secrets
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import select

from apps.api.cache import client
from apps.api.security import admin
from packages.database import models as m
from packages.database.session import get_session
from packages.providers import x_api
from packages.shared import x_publishing as service
from packages.shared.config import settings
from packages.shared.market_config import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/admin/x")


def audit(db, auth, action, key=None):
    db.add(m.Audit(admin_id=auth[0].id, action="x." + action, entity_id=key, changes={}))


def configured():
    c = settings()
    if (
        not c.x_enabled
        or not c.x_client_id
        or not c.x_client_secret.get_secret_value()
        or c.x_redirect_uri != c.public_origin.rstrip("/") + "/api/v1/admin/x/callback"
        or not c.x_redirect_uri.startswith("https://")
        or len(c.config_encryption_key.get_secret_value()) < 32
    ):
        raise HTTPException(
            409, "Configure X credentials, encryption and the exact HTTPS callback on the server."
        )
    return c


@router.get("")
async def overview(auth=Depends(admin), db=Depends(get_session)):
    a = await service.account(db)
    rows = (await db.scalars(select(m.XPost).order_by(m.XPost.created_at.desc()).limit(50))).all()
    await db.commit()
    return {
        "schedules": service.schedules(a),
        "openai_configured": bool(settings().openai_api_key.get_secret_value()),
        "enabled": settings().x_enabled,
        "connected": bool(a.tokens),
        "username": a.username,
        "auto_publish": a.auto_publish,
        "error": a.error_code,
        "monthly_limit": settings().x_monthly_post_limit,
        "daily_limit": settings().x_daily_attempt_limit,
        "posts": [
            {
                "has_image": bool(row.image_png),
                **{
                    k: getattr(row, k)
                    for k in (
                        "kind",
                        "id",
                        "content",
                        "status",
                        "evidence",
                        "post_id",
                        "created_at",
                        "approved_at",
                        "published_at",
                        "attempted_at",
                        "attempts",
                        "error_code",
                        "api_status",
                        "request_id",
                    )
                },
            }
            for row in rows
        ],
    }


@router.post("/connect")
async def connect(auth=Depends(admin), db=Depends(get_session)):
    c = configured()
    # One outstanding flow per administrator session; opaque secrets remain encrypted in Redis.
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    key = "x:oauth:" + auth[1].id
    await client.set(
        key, encrypt_secret(json.dumps({"state": state, "verifier": verifier})), ex=600
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    audit(db, auth, "connect_started")
    await db.commit()
    return {
        "url": "https://x.com/i/oauth2/authorize?"
        + urlencode(
            dict(
                response_type="code",
                client_id=c.x_client_id,
                redirect_uri=c.x_redirect_uri,
                scope=x_api.SCOPES,
                state=state,
                code_challenge=challenge,
                code_challenge_method="S256",
            )
        )
    }


@router.get("/callback")
async def callback(
    state: str = Query("", max_length=200),
    code: str = Query("", max_length=2048),
    error: str = Query("", max_length=100),
    auth=Depends(admin),
    db=Depends(get_session),
):
    c = configured()
    raw = await client.getdel("x:oauth:" + auth[1].id)
    if not raw:
        raise HTTPException(400, "X connection expired. Start again.")
    flow = json.loads(decrypt_secret(raw))
    if not secrets.compare_digest(state, flow["state"]) or error or not code:
        raise HTTPException(400, "X authorization was declined or invalid. Start again.")
    try:
        async with service.operation_lock():
            a = await service.account(db)
            tokens = await x_api.exchange(
                dict(
                    grant_type="authorization_code",
                    code=code,
                    redirect_uri=c.x_redirect_uri,
                    code_verifier=flow["verifier"],
                )
            )
            user = await x_api.identity(tokens["access_token"])
            if a.user_id and a.user_id != user["id"]:
                raise x_api.XError("ACCOUNT_ID_CHANGED")
            x_api.save_tokens(a, tokens)
            a.user_id, a.username, a.connected_at = user["id"], user["username"], m.now()
            a.auto_publish = False
            audit(db, auth, "connected")
            await db.commit()
    except x_api.XError as exc:
        raise HTTPException(409, exc.code) from None
    return RedirectResponse(
        c.public_origin.rstrip("/") + "/meraadmin",
        status_code=303,
        headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"},
    )


@router.post("/disconnect")
async def disconnect(auth=Depends(admin), db=Depends(get_session)):
    async with service.operation_lock():
        a = await service.account(db)
        error = None
        if a.tokens:
            tokens = json.loads(decrypt_secret(a.tokens))
            try:
                c = settings()
                await x_api.request(
                    "POST",
                    "/2/oauth2/revoke",
                    data={
                        "token": tokens["refresh_token"],
                        "client_id": c.x_client_id,
                        "token_type_hint": "refresh_token",
                    },
                    auth=(c.x_client_id, c.x_client_secret.get_secret_value()),
                )
            except x_api.XError:
                error = "REVOCATION_UNCONFIRMED_REVOKE_IN_X_SETTINGS"
        a.tokens = a.expires_at = None
        a.auto_publish, a.error_code = False, error
        audit(db, auth, "disconnected")
        await db.commit()
    return {"message": error or "Disconnected. Automatic publishing is off."}


class AutoInput(BaseModel):
    enabled: StrictBool


class ScheduleInput(BaseModel):
    kind: Literal["MARKET_DAILY", "IPO_OPENING"]
    enabled: StrictBool
    time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


@router.post("/schedule")
async def save_schedule(data: ScheduleInput, auth=Depends(admin), db=Depends(get_session)):
    async with service.operation_lock():
        a = await service.account(db)
        value = service.schedules(a)
        value[data.kind] = {**value[data.kind], "enabled": data.enabled, "time": data.time}
        a.schedules = value
        audit(db, auth, "schedule_changed", data.kind)
        await db.commit()
    return {"message": "Schedule saved in IST. Disabled types also block queued publishing."}


@router.post("/market-auto")
async def market_auto(data: AutoInput, auth=Depends(admin), db=Depends(get_session)):
    async with service.operation_lock():
        a = await service.account(db)
        if data.enabled:
            configured()
            if not a.tokens or not await db.scalar(
                select(m.XPost.id)
                .where(
                    m.XPost.kind == "MARKET_DAILY",
                    m.XPost.status == "PUBLISHED",
                    m.XPost.approved_at.is_not(None),
                )
                .limit(1)
            ):
                raise HTTPException(
                    409,
                    "First review and successfully publish an approved daily market update. Automatic research can still contain errors; retain source monitoring.",
                )
        value = service.schedules(a)
        value["MARKET_DAILY"]["auto_publish"] = data.enabled
        a.schedules = value
        audit(db, auth, "market_auto_on" if data.enabled else "market_auto_off")
        await db.commit()
    return {
        "message": "Market automation preference saved. The global auto-publish control must also be enabled."
    }


class GenerateInput(BaseModel):
    kind: Literal["MARKET_DAILY", "IPO_OPENING"]


@router.post("/generate")
async def generate_type(data: GenerateInput, auth=Depends(admin), db=Depends(get_session)):
    configured()
    async with service.operation_lock():
        rows = await service.generate_scheduled(db, data.kind, manual=True)
        audit(db, auth, "generate", data.kind)
        await db.commit()
    return {
        "message": (rows[0].error_code or "Draft created.")
        if rows
        else "No new eligible draft. Check enabled state, trading calendar and today's ledger."
    }


@router.get("/{key}/image")
async def image(key: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.XPost, key)
    if not row or not row.image_png:
        raise HTTPException(404, "Image unavailable")
    return Response(row.image_png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/auto")
async def auto(data: AutoInput, auth=Depends(admin), db=Depends(get_session)):
    async with service.operation_lock():
        a = await service.account(db)
        if data.enabled:
            configured()
            if not a.tokens or not await db.scalar(
                select(m.XPost.id).where(m.XPost.status == "PUBLISHED").limit(1)
            ):
                raise HTTPException(
                    409,
                    "Connect @MeraIPO and successfully publish an approved post before enabling automatic publishing.",
                )
        a.auto_publish = data.enabled
        audit(db, auth, "auto_on" if data.enabled else "auto_off")
        await db.commit()
    return {"message": "Publishing mode saved."}


@router.post("/draft")
async def draft(auth=Depends(admin), db=Depends(get_session)):
    async with service.operation_lock():
        row = await service.generate(db)
        audit(db, auth, "draft", row.id)
        await db.commit()
    return {"message": row.error_code or "Draft ready for approval."}


@router.post("/{key}/approve")
async def approve(key: str, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.XPost, key, with_for_update=True)
    if not row or row.status not in ("DRAFT", "FAILED"):
        raise HTTPException(409, "Only a draft or definitively failed post can be approved.")
    try:
        await service.validate_post(db, row)
    except x_api.XError as exc:
        raise HTTPException(409, exc.code) from None
    row.status, row.approved_by, row.approved_at = "APPROVED", auth[0].id, m.now()
    audit(db, auth, "approved", row.id)
    await db.commit()
    return {"message": "Approved. Use Publish now to post."}


@router.post("/{key}/publish")
async def publish_now(key: str, auth=Depends(admin), db=Depends(get_session)):
    configured()
    row = await db.get(m.XPost, key, with_for_update=True)
    if not row or row.status != "APPROVED":
        raise HTTPException(409, "Approve this draft first.")
    row.status = "QUEUED"
    audit(db, auth, "publish_requested", row.id)
    await db.commit()
    # The minute outbox recovers broker failures without losing or duplicating the request.
    return {
        "message": "Queued for publishing. The worker will recheck sources and spending limits."
    }

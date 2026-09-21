import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api import cache, schemas, security, services
from apps.api import repository as repo
from apps.api.feedback_routes import router as feedback_router
from apps.api.market_routes import router as market_router
from packages.database import models as m
from packages.database.session import engine, get_session
from packages.shared.calculations import financial_quarter, financial_year
from packages.shared.config import settings

logger = logging.getLogger("meraipo")
logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app):
    settings()
    yield
    await engine.dispose()
    await cache.client.aclose()


app = FastAPI(
    title="MeraIPO API",
    version="1.0",
    docs_url=None if settings().environment == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings().environment == "production" else "/openapi.json",
    lifespan=lifespan,
)
app.include_router(market_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")


@app.middleware("http")
async def observe(request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    try:
        declared_length = int(request.headers.get("content-length", "0") or "0")
    except ValueError:
        return JSONResponse({"error": {"message": "Invalid Content-Length"}}, status_code=400)
    if declared_length > 1_048_576:
        return JSONResponse(
            {
                "error": {
                    "code": "too_large",
                    "message": "Request exceeds 1 MB",
                    "request_id": request_id,
                }
            },
            status_code=413,
        )
    if request.method in ("POST", "PUT", "PATCH"):
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 1_048_576:
                return JSONResponse({"error": {"message": "Request exceeds 1 MB"}}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(json.dumps({"event": "request_failed", "request_id": request_id}))
        response = JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Temporarily unavailable",
                    "request_id": request_id,
                }
            },
            status_code=500,
        )
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
    )
    if settings().environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = (
        "no-store"
        if "/admin" in request.url.path or request.url.path.startswith("/api/v1/feedback")
        else (
            "public, max-age=30"
            if request.method == "GET"
            and response.status_code == 200
            and request.url.path.startswith("/api/v1")
            else "no-store"
        )
    )
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": str(exc.status_code),
                "message": str(exc.detail),
                "request_id": getattr(request.state, "request_id", None),
            }
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "Check the submitted values",
                "fields": [
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in exc.errors()
                ],
                "request_id": getattr(request.state, "request_id", None),
            }
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "conflict",
                "message": "A record with this identity already exists. Refresh and retry.",
            }
        },
        status_code=409,
    )


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_session)):
    try:
        await db.execute(text("SELECT 1"))
        await cache.client.ping()
    except Exception:
        raise HTTPException(503, "Database or cache unavailable") from None
    return {"status": "ready"}


async def read_catalog(db):
    if settings().environment == "test":
        return await repo.catalog(db)
    return await cache.cached("catalog", lambda: repo.catalog(db))


@app.get("/api/v1/ipos/{status}")
async def ipos(status: str, db: AsyncSession = Depends(get_session)):
    if status not in ("open", "upcoming", "recent"):
        result = await repo.journey(db, status)
        if not result:
            raise HTTPException(404, "Company not found")
        return result
    values = {"open": ["OPEN"], "upcoming": ["UPCOMING"], "recent": ["CLOSED", "LISTED"]}[status]
    return {
        "items": [c for c in await read_catalog(db) if c["status"] in values],
        "demo": settings().demo_mode,
    }


@app.get("/api/v1/tracker")
async def tracker(
    fy: int | None = Query(None, ge=2000, le=2100),
    quarter: int | None = Query(None, ge=1, le=4),
    board: Literal["Mainboard", "SME"] | None = None,
    sector: str | None = Query(None, max_length=120),
    view: Literal[
        "recent",
        "improving",
        "corrected",
        "improving-corrected",
        "below-ipo",
        "high-growth",
        "pending",
    ] = "recent",
    quality: Literal["VERIFIED", "PARTIAL", "STALE", "UNVERIFIED", "CONFLICT"] | None = None,
    trend: Literal["IMPROVING", "STABLE", "WEAKENING", "INSUFFICIENT_DATA"] | None = None,
    min_return: float | None = None,
    max_return: float | None = None,
    min_drawdown: float | None = None,
    max_drawdown: float | None = None,
    min_revenue_growth: float | None = None,
    min_pat_growth: float | None = None,
    min_roce: float | None = None,
    max_debt: float | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    if min_return is not None and max_return is not None and min_return > max_return:
        raise HTTPException(422, "Minimum return cannot exceed maximum")
    all_items = [c for c in await read_catalog(db) if c["status"] == "LISTED"]
    items = []
    for c in all_items:
        if (
            fy
            and c["listing_fy"] != fy
            or quarter
            and c["listing_quarter"] != quarter
            or board
            and c["board"] != board
            or sector
            and c["sector"] != sector
            or quality
            and c["quality"] != quality
            or trend
            and c["trend"]["state"] != trend
        ):
            continue
        checks = [
            (c["return_ipo"], min_return, "min"),
            (c["return_ipo"], max_return, "max"),
            (c["drawdown"], min_drawdown, "min"),
            (c["drawdown"], max_drawdown, "max"),
            (c["latest"].get("revenue_yoy"), min_revenue_growth, "min"),
            (c["latest"].get("pat_yoy"), min_pat_growth, "min"),
            (c["latest"].get("roce"), min_roce, "min"),
            (c["latest"].get("debt"), max_debt, "max"),
        ]
        if any(
            limit is not None
            and (value is None or (value < limit if direction == "min" else value > limit))
            for value, limit, direction in checks
        ):
            continue
        improving = c["trend"]["state"] == "IMPROVING"
        corrected = c["drawdown"] is not None and c["drawdown"] <= -20
        if (
            view == "improving"
            and not improving
            or view == "corrected"
            and not corrected
            or view == "improving-corrected"
            and not (improving and corrected)
            or view == "below-ipo"
            and not (c["return_ipo"] is not None and c["return_ipo"] < 0)
            or view == "high-growth"
            and not (
                c["latest"].get("revenue_yoy") is not None and c["latest"]["revenue_yoy"] >= 20
            )
            or view == "pending"
            and c["trend"]["state"] != "INSUFFICIENT_DATA"
        ):
            continue
        items.append(c)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "financial_years": sorted(
            {c["listing_fy"] for c in all_items if c["listing_fy"]}, reverse=True
        ),
        "sectors": sorted({c["sector"] for c in all_items}),
        "demo": settings().demo_mode,
        "current_fy": financial_year(date.today()),
        "current_quarter": financial_quarter(date.today()),
    }


@app.get("/api/v1/companies/{slug}")
@app.get("/api/v1/companies/{slug}/journey")
async def company(slug: str, db: AsyncSession = Depends(get_session)):
    result = await repo.journey(db, slug)
    if not result:
        raise HTTPException(404, "Company not found")
    return result


@app.get("/api/v1/companies/{slug}/{section}")
async def company_section(
    slug: str,
    section: Literal["quarters", "prices", "valuation"],
    db: AsyncSession = Depends(get_session),
):
    result = await company(slug, db)
    return {"items": result[section]}


@app.get("/api/v1/site/message")
async def site_message(db: AsyncSession = Depends(get_session)):
    now = m.now()
    message = await db.scalar(
        select(m.SiteMessage)
        .where(
            m.SiteMessage.enabled.is_(True),
            (m.SiteMessage.active_from.is_(None) | (m.SiteMessage.active_from <= now)),
            (m.SiteMessage.active_to.is_(None) | (m.SiteMessage.active_to > now)),
        )
        .order_by(m.SiteMessage.updated_at.desc())
        .limit(1)
    )
    return {"message": repo.record(message) if message else None}


@app.get("/api/v1/site/advertisements")
async def advertisements(
    placement: Literal["home", "tracker"] = "home", db: AsyncSession = Depends(get_session)
):
    return {
        "items": [
            repo.record(ad)
            for ad in (
                await db.scalars(
                    select(m.Advertisement).where(
                        m.Advertisement.enabled.is_(True), m.Advertisement.placement == placement
                    )
                )
            ).all()
        ]
    }


@app.post("/api/v1/admin/login")
async def login(
    data: schemas.LoginInput,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    if request.headers.get("origin") != settings().public_origin:
        raise HTTPException(403, "Invalid request origin")
    await security.login_limit(request, data.email)
    user = await db.scalar(select(m.AdminUser).where(m.AdminUser.email == data.email.lower()))
    valid = security.verify(data.password, user.password_hash if user else security.dummy_hash)
    if not user or not user.enabled or not valid:
        raise HTTPException(401, "Invalid email or password")
    token, csrf = await security.new_session(db, user)
    db.add(m.Audit(admin_id=user.id, action="admin.login", changes={}))
    await db.commit()
    for name, value in (("mera_session", token), ("mera_csrf", csrf)):
        response.set_cookie(
            name,
            value,
            httponly=True,
            secure=settings().environment == "production",
            samesite="lax",
            max_age=settings().session_hours * 3600,
            path="/api/v1/admin",
        )
    return {"email": user.email, "csrf_token": csrf}


@app.get("/api/v1/admin/session")
async def session_info(request: Request, auth=Depends(security.admin)):
    return {"email": auth[0].email, "csrf_token": request.cookies.get("mera_csrf")}


@app.post("/api/v1/admin/logout")
async def logout(
    response: Response, auth=Depends(security.admin), db: AsyncSession = Depends(get_session)
):
    await db.delete(auth[1])
    db.add(m.Audit(admin_id=auth[0].id, action="admin.logout", changes={}))
    await db.commit()
    response.delete_cookie("mera_session", path="/api/v1/admin")
    response.delete_cookie("mera_csrf", path="/api/v1/admin")
    return {"ok": True}


async def commit(db):
    await db.flush()
    await cache.commit_with_invalidation(db)


@app.post("/api/v1/admin/companies/{slug}/quarters/import")
async def import_quarters(
    slug: str,
    data: list[schemas.QuarterInput] = Body(min_length=1, max_length=100),
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    results = []
    for row in data:
        result, created = await services.add_quarter(db, slug, row, auth[0].id)
        results.append({"id": result.id, "created": created, "revision": result.revision})
    await commit(db)
    return {"items": results}


@app.put("/api/v1/admin/ipos/{slug}/applicant-guide")
async def save_applicant_guide(
    slug: str,
    data: schemas.ApplicantGuideInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    ipo = await db.scalar(select(m.IPO).join(m.Company).where(m.Company.slug == slug))
    if not ipo:
        raise HTTPException(404, "Company not found")
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo.id))
    if (
        dates
        and dates.close_date
        and data.allotment_date
        and data.allotment_date < dates.close_date
    ):
        raise HTTPException(422, "Allotment must not precede issue close")
    if (
        dates
        and dates.listing_date
        and data.allotment_date
        and data.allotment_date > dates.listing_date
    ):
        raise HTTPException(422, "Allotment must not follow listing")
    if data.min_lots and data.max_amount and ipo.price_high and ipo.lot_size:
        if ipo.price_high * ipo.lot_size * data.min_lots > data.max_amount:
            raise HTTPException(422, "Minimum application exceeds this category's amount limit")
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    before = repo.record(guide) if guide else None
    if not guide:
        guide = m.ApplicantGuide(ipo_id=ipo.id)
        db.add(guide)
    for key, value in data.model_dump().items():
        if key not in ("provider", "source_timestamp"):
            setattr(guide, key, value)
    await db.flush()
    await services.provenance(db, guide, data)
    services.audit(db, auth[0].id, "applicant_guide_updated", guide, before)
    await commit(db)
    return repo.record(guide)


@app.get("/api/v1/admin/dashboard")
async def dashboard(auth=Depends(security.admin), db: AsyncSession = Depends(get_session)):
    items = await repo.catalog(db)
    runs = [
        repo.record(r)
        for r in (
            await db.scalars(select(m.ImportRun).order_by(m.ImportRun.updated_at.desc()).limit(20))
        ).all()
    ]
    return {
        "active": sum(c["status"] == "OPEN" for c in items),
        "upcoming": sum(c["status"] == "UPCOMING" for c in items),
        "tracked": sum(c["status"] == "LISTED" for c in items),
        "missing_results": sum(c["status"] == "LISTED" and not c["latest"] for c in items),
        "missing_symbols": sum(not c["ticker"] for c in items),
        "missing_ipo_data": sum(c["price_high"] is None for c in items),
        "stale_gmp": sum(c["gmp_quality"] == "STALE" for c in items),
        "stale_prices": sum(
            c["status"] == "LISTED"
            and (
                not c["price_date"] or (date.today() - date.fromisoformat(c["price_date"])).days > 3
            )
            for c in items
        ),
        "conflicts": sum(c["quality"] == "CONFLICT" for c in items),
        "failed_jobs": sum(r["status"] == "FAILED" for r in runs),
        "provider_mode": settings().provider_mode,
        "imports": runs,
        "companies": items,
    }


@app.post("/api/v1/admin/ipos", status_code=201)
async def create_ipo(
    data: schemas.IPOInput, auth=Depends(security.admin), db: AsyncSession = Depends(get_session)
):
    result = await services.maintain_ipo(db, data, auth[0].id)
    await commit(db)
    return {"id": result.id, "slug": result.slug}


@app.put("/api/v1/admin/ipos/{slug}")
async def edit_ipo(
    slug: str,
    data: schemas.IPOInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result = await services.maintain_ipo(db, data, auth[0].id, slug)
    await commit(db)
    return {"id": result.id, "slug": result.slug}


@app.post("/api/v1/admin/companies/{slug}/quarters")
async def add_quarter(
    slug: str,
    data: schemas.QuarterInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result, created = await services.add_quarter(db, slug, data, auth[0].id)
    await commit(db)
    return {"id": result.id, "created": created, "revision": result.revision}


@app.post("/api/v1/admin/ipos/{slug}/gmp")
async def add_gmp(
    slug: str,
    data: schemas.GMPInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result, created = await services.add_gmp(db, slug, data, auth[0].id)
    await commit(db)
    return {"id": result.id, "created": created}


@app.get("/api/v1/admin/messages")
async def messages(auth=Depends(security.admin), db: AsyncSession = Depends(get_session)):
    return {
        "items": [
            repo.record(r)
            for r in (
                await db.scalars(select(m.SiteMessage).order_by(m.SiteMessage.updated_at.desc()))
            ).all()
        ]
    }


@app.post("/api/v1/admin/messages", status_code=201)
async def create_message(
    data: schemas.MessageInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result = m.SiteMessage(**data.model_dump())
    db.add(result)
    await db.flush()
    services.audit(db, auth[0].id, "message.create", result)
    await commit(db)
    return repo.record(result)


@app.put("/api/v1/admin/messages/{item_id}")
async def edit_message(
    item_id: str,
    data: schemas.MessageInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result = await db.get(m.SiteMessage, item_id)
    if not result:
        raise HTTPException(404, "Message not found")
    before = repo.record(result)
    for key, value in data.model_dump().items():
        setattr(result, key, value)
    await db.flush()
    services.audit(db, auth[0].id, "message.update", result, before)
    await commit(db)
    return repo.record(result)


@app.get("/api/v1/admin/advertisements")
async def admin_ads(auth=Depends(security.admin), db: AsyncSession = Depends(get_session)):
    return {"items": [repo.record(r) for r in (await db.scalars(select(m.Advertisement))).all()]}


@app.post("/api/v1/admin/advertisements", status_code=201)
async def create_ad(
    data: schemas.AdInput, auth=Depends(security.admin), db: AsyncSession = Depends(get_session)
):
    result = m.Advertisement(**data.model_dump())
    db.add(result)
    await db.flush()
    services.audit(db, auth[0].id, "ad.create", result)
    await commit(db)
    return repo.record(result)


@app.put("/api/v1/admin/advertisements/{item_id}")
async def edit_ad(
    item_id: str,
    data: schemas.AdInput,
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    result = await db.get(m.Advertisement, item_id)
    if not result:
        raise HTTPException(404, "Advertisement not found")
    before = repo.record(result)
    for key, value in data.model_dump().items():
        setattr(result, key, value)
    await db.flush()
    services.audit(db, auth[0].id, "ad.update", result, before)
    await commit(db)
    return repo.record(result)


@app.get("/api/v1/admin/audit")
async def audits(
    page: int = Query(1, ge=1),
    auth=Depends(security.admin),
    db: AsyncSession = Depends(get_session),
):
    return {
        "items": [
            repo.record(r)
            for r in (
                await db.scalars(
                    select(m.Audit)
                    .order_by(m.Audit.created_at.desc())
                    .offset((page - 1) * 50)
                    .limit(50)
                )
            ).all()
        ]
    }

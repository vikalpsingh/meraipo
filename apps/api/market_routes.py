import json
import secrets
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select, update

from apps.api import schemas
from apps.api.repository import record
from apps.api.schemas import Input
from apps.api.security import admin
from apps.worker.exchange_pipeline import PIPELINE_JOBS
from apps.worker.market import JOBS, create_run
from packages.database import models as m
from packages.database.session import get_session
from packages.providers.bse_ipo import configuration as bse_configuration
from packages.providers.exchanges import discovery_sources
from packages.providers.market import configuration
from packages.shared.config import settings
from packages.shared.market_config import (
    CONFIG_ID,
    EDITABLE_FIELDS,
    encrypt_secret,
    load_market_settings,
)
from packages.shared.market_freshness import freshness, next_scheduled

router = APIRouter()
ALL_JOBS = {**JOBS, **PIPELINE_JOBS}


@router.get("/admin/market/errors")
async def error_log(auth=Depends(admin), db=Depends(get_session)):
    rows = (
        await db.execute(
            select(m.JobError, m.ImportRun.job_name, m.ImportRun.status)
            .join(m.ImportRun, m.ImportRun.id == m.JobError.run_id)
            .order_by(m.JobError.created_at.desc(), m.JobError.id.desc())
            .limit(50)
        )
    ).all()
    return {
        "items": [
            {**record(error), "job_name": job, "run_status": status} for error, job, status in rows
        ]
    }


class RunRequest(Input):
    retry_rejected: bool = False
    company_id: str | None = Field(None, max_length=36)
    from_date: date | None = None
    to_date: date | None = None
    confirm_backfill: bool = False


class PauseRequest(Input):
    paused: bool


async def dispatch(db, job, trigger, data):
    if job not in ALL_JOBS:
        raise HTTPException(404, "Unknown market job")
    runtime = await load_market_settings(db)
    if trigger == "scheduled" and not runtime.market_scheduler_enabled:
        raise HTTPException(503, "Enable MARKET_SCHEDULER_ENABLED after completing setup")
    params = {}
    if job in ("sync-prices", "collect-prices") and data.to_date:
        if data.to_date > date.today() or (data.from_date and data.from_date != data.to_date):
            raise HTTPException(422, "Choose one non-future trading date")
        params["trade_date"] = data.to_date.isoformat()
    if data.retry_rejected:
        if not job.startswith(("publish-", "sync-")):
            raise HTTPException(422, "Retry rejected records with a publishing job")
        params["retry_rejected"] = True
    if data.company_id:
        company = await db.get(m.Company, data.company_id)
        if not company or company.is_demo:
            raise HTTPException(422, "Choose a tracked, non-demo company")
        params["company_id"] = data.company_id
    if job == "backfill":
        if not (data.confirm_backfill and data.company_id and data.from_date and data.to_date):
            raise HTTPException(422, "Confirm a company and bounded date range for backfill")
        if data.to_date > date.today() or not 0 <= (data.to_date - data.from_date).days <= 366:
            raise HTTPException(422, "Backfill one year at a time; future dates are not allowed")
        params.update({"from": data.from_date.isoformat(), "to": data.to_date.isoformat()})
    run = await create_run(db, job, trigger, params)
    try:
        from apps.worker.tasks import market_job

        market_job.delay(run.id)
    except Exception:
        run.status, run.error, run.finished_at = (
            "FAILED",
            "QUEUE_UNAVAILABLE: check Redis and worker",
            m.now(),
        )
        await db.commit()
        raise HTTPException(503, "Worker queue unavailable; failed attempt recorded") from None
    return {"id": run.id, "status": run.status}


@router.post("/internal/cron/{job}", status_code=202)
async def cron(job: str, request: Request, db=Depends(get_session)):
    secret = settings().cron_secret
    if len(secret) < 32 or not secrets.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + secret
    ):
        raise HTTPException(401, "Invalid cron authentication")
    if job == "backfill":
        raise HTTPException(404, "Manual job only")
    runtime = await load_market_settings(db)
    if runtime.market_scheduler_driver != "vercel":
        raise HTTPException(409, "Celery owns scheduling; Vercel scheduling is disabled")
    return await dispatch(db, job, "scheduled", RunRequest())


def configuration_response(config, row):
    try:
        feeds = json.loads(config.market_feeds_json or "{}")
        for group in feeds.values():
            for provider in group.values():
                if provider.get("token"):
                    provider["token"] = "********"
        safe_feeds = json.dumps(feeds, indent=2)
    except (TypeError, ValueError):
        safe_feeds = config.market_feeds_json
    return {
        **{key: getattr(config, key) for key in EDITABLE_FIELDS},
        "market_feeds_json": safe_feeds,
        "ipoalerts_api_key_configured": bool(config.ipoalerts_api_key.get_secret_value()),
        "source": "admin" if row else "environment",
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.get("/admin/market/config")
async def get_market_configuration(auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.MarketConfiguration, CONFIG_ID)
    try:
        config = await load_market_settings(db)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    return configuration_response(config, row)


@router.put("/admin/market/config")
async def save_market_configuration(
    data: schemas.MarketConfigurationInput,
    auth=Depends(admin),
    db=Depends(get_session),
):
    current = await load_market_settings(db)
    values = data.model_dump(
        exclude={"ipoalerts_api_key", "clear_ipoalerts_api_key", "market_feeds_json"}
    )
    submitted_feeds = json.loads(data.market_feeds_json)
    current_feeds = json.loads(current.market_feeds_json or "{}")
    for kind, group in submitted_feeds.items():
        for name, provider in group.items():
            if provider.get("token") == "********":
                provider["token"] = current_feeds.get(kind, {}).get(name, {}).get("token", "")
    market_feeds_json = json.dumps(submitted_feeds, separators=(",", ":"))
    try:
        configuration(market_feeds_json)
        discovery_sources(values["exchange_sources_json"])
        bse_configuration(values["bse_ipo_issues_json"])
    except Exception as exc:
        raise HTTPException(422, f"Provider configuration is invalid: {exc}") from exc
    row = await db.get(m.MarketConfiguration, CONFIG_ID)
    before = dict(row.values) if row else None
    if not row:
        row = m.MarketConfiguration(id=CONFIG_ID, values={})
        db.add(row)
    row.values = values
    row.updated_by = auth[0].id
    try:
        row.market_feeds_json_encrypted = encrypt_secret(market_feeds_json)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if data.clear_ipoalerts_api_key:
        row.ipoalerts_api_key_encrypted = None
    elif data.ipoalerts_api_key:
        try:
            row.ipoalerts_api_key_encrypted = encrypt_secret(data.ipoalerts_api_key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.config.update",
            entity_id=CONFIG_ID,
            changes={
                "before": before,
                "after": values,
                "api_key_changed": bool(data.ipoalerts_api_key or data.clear_ipoalerts_api_key),
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return configuration_response(await load_market_settings(db), row)


@router.get("/admin/market")
async def overview(auth=Depends(admin), db=Depends(get_session)):
    config = await load_market_settings(db)
    # Recover visibility after a worker crash without pretending it completed.
    await db.execute(
        update(m.ImportRun)
        .where(
            m.ImportRun.job_name.is_not(None),
            m.ImportRun.status.in_(["RUNNING", "QUEUED"]),
            m.ImportRun.updated_at < m.now() - timedelta(minutes=10),
        )
        .values(
            status="FAILED",
            error="WORKER_TIMEOUT: retry after checking worker health",
            finished_at=m.now(),
        )
    )
    await db.commit()
    runs = (
        await db.scalars(
            select(m.ImportRun)
            .where(m.ImportRun.job_name.is_not(None))
            .order_by(m.ImportRun.created_at.desc())
            .limit(50)
        )
    ).all()
    controls = {c.name: c.paused for c in (await db.scalars(select(m.SchedulerControl))).all()}
    try:
        feeds = configuration(config.market_feeds_json)
        native = discovery_sources(config.exchange_sources_json)
        bse_issues = bse_configuration(config.bse_ipo_issues_json)
        config_error = None
    except Exception:
        feeds, native, config_error = (
            {},
            [],
            "Invalid provider configuration; check MARKET_FEEDS_JSON and EXCHANGE_SOURCES_JSON",
        )
        bse_issues = []
    providers = [
        {
            "kind": kind,
            "name": name,
            "authority": c.authority,
            "enabled": c.enabled,
            "credential_set": bool(c.token),
        }
        for kind, group in feeds.items()
        for name, c in group.items()
    ]
    if config.ipo_data_provider == "ipoalerts":
        providers = [p for p in providers if p["kind"] != "ipos"]
        providers.append(
            {
                "kind": "ipos",
                "name": "IPOALERTS",
                "authority": "LICENSED",
                "enabled": True,
                "credential_set": bool(config.ipoalerts_api_key.get_secret_value()),
            }
        )
        providers.append(
            {
                "kind": "gmp",
                "name": "IPOALERTS",
                "authority": "UNOFFICIAL",
                "enabled": True,
                "credential_set": bool(config.ipoalerts_api_key.get_secret_value()),
            }
        )
    if config.exchange_direct_enabled:
        providers.extend(
            [
                {
                    "kind": kind,
                    "name": exchange,
                    "authority": "NSE" if exchange == "NSE_CONSOLIDATED" else exchange,
                    "enabled": True,
                    "credential_set": False,
                }
                for kind, exchange in (
                    ("ipos", "NSE"),
                    ("ipos", "BSE"),
                    (
                        "subscriptions",
                        "NSE_CONSOLIDATED" if config.nse_subscription_categories_enabled else "NSE",
                    ),
                    ("prices", "NSE"),
                    ("prices", "BSE"),
                )
                if kind != "ipos" or config.ipo_data_provider == "exchange"
            ]
        )
        providers.extend(
            [
                {
                    "kind": s.kind,
                    "name": s.name,
                    "authority": s.exchange,
                    "enabled": True,
                    "credential_set": False,
                }
                for s in native
            ]
        )
    has_open = await db.scalar(
        select(m.IPO.id)
        .join(m.Company, m.Company.id == m.IPO.company_id)
        .where(m.IPO.status == "OPEN", m.Company.is_demo.is_(False))
        .limit(1)
    )
    for provider in providers:
        latest = await db.scalar(
            select(m.RawPayload)
            .where(
                m.RawPayload.provider == provider["name"],
                m.RawPayload.data_type == provider["kind"],
            )
            .order_by(m.RawPayload.created_at.desc())
            .limit(1)
        )
        if provider["name"] == "IPOALERTS" and provider["kind"] == "gmp":
            latest = await db.scalar(
                select(m.RawPayload)
                .join(m.MarketStage, m.MarketStage.raw_payload_id == m.RawPayload.id)
                .where(m.MarketStage.provider == "IPOALERTS", m.MarketStage.kind == "gmp")
                .order_by(m.RawPayload.created_at.desc())
                .limit(1)
            )
        failure = await db.scalar(
            select(m.JobError)
            .where(
                m.JobError.provider == provider["name"],
                m.JobError.item.like(provider["kind"] + "%"),
            )
            .order_by(m.JobError.created_at.desc())
            .limit(1)
        )
        from packages.shared.calculations import utc

        provider["last_fetched"] = utc(latest.created_at).isoformat() if latest else None
        provider["health"] = freshness(
            provider["kind"],
            latest.created_at if latest else None,
            m.now().astimezone(ZoneInfo("Asia/Kolkata")),
            active=provider["enabled"]
            and (provider["kind"] not in ("gmp", "subscriptions") or bool(has_open)),
            failed=bool(
                failure and (not latest or utc(failure.created_at) > utc(latest.created_at))
            ),
            holidays=config.trading_holidays.split(","),
        )
    return {
        "ipo_data_provider": config.ipo_data_provider,
        "driver": config.market_scheduler_driver,
        "staging": {
            state: await db.scalar(
                select(func.count()).select_from(m.MarketStage).where(m.MarketStage.status == state)
            )
            for state in ("PENDING", "PUBLISHED", "REJECTED", "FALLBACK_NOT_NEEDED")
        },
        "enabled": config.market_scheduler_enabled,
        "setup": [
            {
                "label": "IPO master data provider",
                "ready": config.ipo_data_provider != "ipoalerts"
                or bool(config.ipoalerts_api_key.get_secret_value()),
                "setting": "IPO_DATA_PROVIDER="
                + config.ipo_data_provider
                + "; manage the encrypted IPOAlerts key in Config. GMP uses includeGmp=true when available. NSE consolidated categories are collected independently when direct exchange access is enabled.",
            },
            {
                "label": "BSE category subscriptions",
                "ready": bool(bse_issues),
                "setting": "Config · BSE IPO issue mappings · match each cumulative-demand issue ID to an exact company identifier",
            },
            {
                "label": "Quarterly source mapping",
                "ready": any(s.kind == "results" and s.concepts for s in native)
                or any(c.enabled for c in feeds.get("results", {}).values()),
                "setting": "Config · Exchange sources JSON · verified discovery fields and exact XBRL concept names",
            },
            {
                "label": "Cron authentication",
                "ready": config.market_scheduler_driver == "celery"
                or len(settings().cron_secret) >= 32,
                "setting": "Docker: Celery scheduler; Vercel: shared CRON_SECRET",
            },
            {
                "label": "Provider feeds",
                "ready": config.exchange_direct_enabled or any(p["enabled"] for p in providers),
                "setting": "Config · enable direct exchanges or define licensed feeds",
            },
            {
                "label": "Trading calendar",
                "ready": config.trading_calendar_year == date.today().year,
                "setting": "Config · trading calendar year and holiday dates",
            },
            {
                "label": "Scheduled execution",
                "ready": config.market_scheduler_enabled,
                "setting": "Config · enable scheduled jobs after provider setup",
            },
        ],
        "configuration_error": config_error,
        "providers": providers,
        "jobs": [
            {
                "name": name,
                "label": values[0],
                "schedule": values[1],
                "paused": controls.get(name, False),
                "next_run": (
                    next_scheduled(
                        name,
                        m.now().astimezone(ZoneInfo("Asia/Kolkata")),
                        config.trading_holidays.split(","),
                    )
                    if name.startswith("sync-")
                    and config.market_scheduler_enabled
                    and not controls.get(name, False)
                    else None
                ),
                "last": next((record(r) for r in runs if r.job_name == name), None),
            }
            for name, values in ALL_JOBS.items()
        ],
        "runs": [record(r) for r in runs],
        "errors": [
            record(e)
            for e in (
                await db.scalars(
                    select(m.JobError).order_by(m.JobError.created_at.desc()).limit(30)
                )
            ).all()
        ],
    }


@router.post("/admin/market/{job}/run", status_code=202)
async def manual(job: str, data: RunRequest, auth=Depends(admin), db=Depends(get_session)):
    result = await dispatch(db, job, "manual", data)
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="market.run",
            entity_id=result["id"],
            changes={"job": job, "parameters": data.model_dump(mode="json")},
        )
    )
    await db.commit()
    return result


@router.post("/admin/market/{job}/pause")
async def pause(job: str, data: PauseRequest, auth=Depends(admin), db=Depends(get_session)):
    if job not in ALL_JOBS:
        raise HTTPException(404, "Unknown market job")
    control = await db.get(m.SchedulerControl, job)
    if not control:
        control = m.SchedulerControl(name=job)
        db.add(control)
    control.paused = data.paused
    db.add(
        m.Audit(
            admin_id=auth[0].id, action="market.pause", changes={"job": job, "paused": data.paused}
        )
    )
    await db.commit()
    return {"paused": data.paused}

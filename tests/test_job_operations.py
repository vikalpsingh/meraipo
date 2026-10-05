"""Production-oriented job isolation, schedules, permissions and diagnostics."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from apps.worker.exchange_pipeline import run_pipeline
from apps.worker.market import create_run
from apps.worker.scheduling import claim_due
from packages.database import models as m
from packages.shared.config import settings
from packages.shared.job_schedules import next_slot
from tests.test_bhavcopy import CSV, DAY, config
from tests.test_market_integration import tracked


async def test_independent_schedule_api_and_atomic_due_slots(
    admin_client, db, monkeypatch, tmp_path
):
    config(monkeypatch, tmp_path)
    monkeypatch.setattr(settings(), "market_scheduler_enabled", True)
    monkeypatch.setattr(settings(), "market_scheduler_driver", "celery")
    for job, times in [
        ("sync-prices-nse", ["18:15", "20:00"]),
        ("sync-prices-bse", ["20:00"]),
        ("sync-results-nse", ["20:00"]),
        ("sync-results-bse", ["21:00"]),
    ]:
        r = await admin_client.put(
            f"/api/v1/admin/market/{job}/schedule", json={"times": times, "paused": False}
        )
        assert r.status_code == 200, r.text
    at = datetime(2026, 10, 5, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    ids = await claim_due(db, settings(), at)
    assert len(ids) == 3
    runs = (await db.scalars(select(m.ImportRun).where(m.ImportRun.id.in_(ids)))).all()
    assert {r.job_name for r in runs} == {"sync-prices-nse", "sync-prices-bse", "sync-results-nse"}
    assert await claim_due(db, settings(), at) == []
    assert (await db.get(m.ResultSource, "BSE")).schedule == "21:00"
    assert next_slot(["20:00"], at).startswith("2026-10-06T20:00")
    await admin_client.post("/api/v1/admin/market/sync-prices-nse/pause", json={"paused": True})
    tomorrow = at + timedelta(days=1)
    ids = await claim_due(db, settings(), tomorrow)
    assert len(ids) == 2
    assert (await db.get(m.SchedulerControl, "sync-prices-bse")).paused is False
    monkeypatch.setattr(settings(), "market_scheduler_enabled", False)
    assert await claim_due(db, settings(), tomorrow + timedelta(days=1)) == []


async def test_history_requires_auth(client):
    assert (await client.get("/api/v1/admin/market/runs")).status_code == 401
    assert (await client.get("/api/v1/admin/market/runs/unknown")).status_code == 401


async def test_schedule_validation_and_csrf(admin_client):
    for times in [[], ["25:00"], ["20:00", "20:00"]]:
        assert (
            await admin_client.put(
                "/api/v1/admin/market/sync-prices-nse/schedule",
                json={"times": times, "paused": False},
            )
        ).status_code == 422
    assert (
        await admin_client.put(
            "/api/v1/admin/market/sync-results-nse/schedule",
            json={"times": ["18:00", "20:00"], "paused": False},
        )
    ).status_code == 422
    admin_client.headers.pop("x-csrf-token")
    assert (
        await admin_client.put(
            "/api/v1/admin/market/sync-prices-nse/schedule",
            json={"times": ["20:00"], "paused": False},
        )
    ).status_code == 403


@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
async def test_independent_prices_and_run_diagnostics(
    db, admin_client, monkeypatch, tmp_path, exchange
):
    config(monkeypatch, tmp_path, public_display_allowed=True)
    await tracked(db, "LISTED")
    calls = []

    async def download(url):
        calls.append(url)
        return CSV.replace(b"NSE", exchange.encode())

    run = await create_run(
        db,
        f"sync-prices-{exchange.lower()}",
        "manual",
        {"trade_date": str(DAY), "exchange": "WRONG"},
    )
    await run_pipeline(db, run, download)
    assert run.status == "SUCCESS", run.error
    assert len(calls) == 1 and exchange.lower() in calls[0]
    detail = await admin_client.get(f"/api/v1/admin/market/runs/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["files"][0]["exchange"] == exchange
    assert detail.json()["run"]["counters"]["written"] == 1

    # A different source failure must remain tied to its run.
    async def blocked(url):
        from packages.providers.market import FeedError

        raise FeedError("SOURCE_ACCESS_BLOCKED")

    other = await create_run(
        db, f"sync-prices-{exchange.lower()}", "manual", {"trade_date": str(DAY)}
    )
    await run_pipeline(db, other, blocked)
    assert other.status == "FAILED"
    result = (await admin_client.get(f"/api/v1/admin/market/runs/{other.id}")).json()
    assert result["error_count"] == 1 and "permitted" in result["errors"][0]["guidance"]
    assert (await admin_client.get(f"/api/v1/admin/market/runs/{run.id}")).json()[
        "error_count"
    ] == 0
    history = (
        await admin_client.get(f"/api/v1/admin/market/runs?job={run.job_name}&status=FAILED")
    ).json()
    assert history["total"] == 1 and history["items"][0]["id"] == other.id


async def test_job_card_last_success_is_not_limited_to_recent_50(db, admin_client):
    old = await create_run(db, "sync-results-nse", "manual")
    old.status = "SUCCESS"
    old.finished_at = m.now() - timedelta(days=2)
    old.created_at = old.finished_at
    for index in range(55):
        db.add(
            m.ImportRun(
                key=f"noise-{index}", provider="test", job_name="sync-ipos", status="FAILED"
            )
        )
    await db.commit()
    overview = (await admin_client.get("/api/v1/admin/market")).json()
    job = next(j for j in overview["jobs"] if j["name"] == "sync-results-nse")
    assert job["last_success"]["id"] == old.id and job["last"]["id"] == old.id


@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
async def test_results_job_forces_single_exchange(db, monkeypatch, exchange):
    from apps.worker import results

    seen = []

    async def sync(db, run, counts):
        seen.extend(run.parameters["exchanges"])
        counts["providers"] = 1

    monkeypatch.setattr(results, "sync", sync)
    run = await create_run(
        db, f"sync-results-{exchange.lower()}", "manual", {"exchanges": ["NSE", "BSE"]}
    )
    await run_pipeline(db, run)
    assert seen == [exchange] and run.status == "SUCCESS"


async def test_migration_defaults_honor_parent_pause_and_disabled_sources(
    db, monkeypatch, tmp_path
):
    config(monkeypatch, tmp_path)
    monkeypatch.setattr(settings(), "market_scheduler_enabled", True)
    monkeypatch.setattr(settings(), "market_scheduler_driver", "celery")
    db.add(m.SchedulerControl(name="sync-prices", paused=True))
    db.add(m.ResultSource(exchange="BSE", enabled=False, schedule="19:30"))
    await db.commit()
    at = datetime(2026, 10, 5, 19, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert await claim_due(db, settings(), at) == []
    ids = await claim_due(db, settings(), at.replace(hour=21, minute=0))
    assert len(ids) == 1
    assert (await db.get(m.ImportRun, ids[0])).job_name == "sync-results-nse"


async def test_manual_exchange_dispatch_dates_and_queue_failure(
    admin_client, db, monkeypatch, tmp_path
):
    from apps.worker.tasks import market_job

    config(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(market_job, "delay", lambda run_id: queued.append(run_id))
    response = await admin_client.post(
        "/api/v1/admin/market/sync-prices-nse/run", json={"to_date": "2026-07-20"}
    )
    assert response.status_code == 202, response.text
    run = await db.get(m.ImportRun, response.json()["id"])
    assert run.parameters == {"exchange": "NSE", "trade_date": "2026-07-20"}
    assert queued == [run.id]
    assert (
        await admin_client.post("/api/v1/admin/market/sync-prices-nse/run", json={})
    ).status_code == 409
    assert (
        await admin_client.post(
            "/api/v1/admin/market/sync-results-bse/run", json={"from_date": "2026-07-20"}
        )
    ).status_code == 422

    def unavailable(run_id):
        raise ConnectionError("test queue unavailable")

    monkeypatch.setattr(market_job, "delay", unavailable)
    response = await admin_client.post("/api/v1/admin/market/sync-results-bse/run", json={})
    assert response.status_code == 503
    failed = await db.scalar(select(m.ImportRun).where(m.ImportRun.job_name == "sync-results-bse"))
    assert failed.status == "FAILED" and failed.finished_at is not None


@pytest.mark.parametrize(
    "frequency,times,weekday,at,expected",
    [
        ("hourly", ["00:15"], 0, "2026-10-05T19:14:00+05:30", "2026-10-05T19:15:00+05:30"),
        ("hourly", ["00:15"], 0, "2026-10-05T23:15:00+05:30", "2026-10-06T00:15:00+05:30"),
        ("weekly", ["20:00"], 4, "2026-10-05T19:00:00+05:30", "2026-10-09T20:00:00+05:30"),
        ("weekly", ["20:00"], 0, "2026-10-05T20:00:00+05:30", "2026-10-12T20:00:00+05:30"),
    ],
)
def test_frequency_next_run(frequency, times, weekday, at, expected):
    from packages.shared.job_schedules import is_due

    at = datetime.fromisoformat(at)
    assert next_slot(times, at, frequency, weekday) == expected
    assert is_due(
        {"frequency": frequency, "times": times, "weekday": weekday},
        datetime.fromisoformat(expected),
    )


async def test_hourly_weekly_and_ipo_schedules(admin_client, db, monkeypatch, tmp_path):
    config(monkeypatch, tmp_path)
    monkeypatch.setattr(settings(), "market_scheduler_enabled", True)
    monkeypatch.setattr(settings(), "market_scheduler_driver", "celery")
    for job, frequency, times, weekday in [
        ("sync-ipos", "hourly", ["00:15"], 0),
        ("sync-results-nse", "weekly", ["20:15"], 4),
    ]:
        r = await admin_client.put(
            f"/api/v1/admin/market/{job}/schedule",
            json={"times": times, "paused": False, "frequency": frequency, "weekday": weekday},
        )
        assert r.status_code == 200, r.text
        assert r.json()["frequency"] == frequency
    monday = datetime(2026, 10, 5, 20, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    ids = await claim_due(db, settings(), monday)
    assert [(await db.get(m.ImportRun, id)).job_name for id in ids] == ["sync-ipos"]
    ids = await claim_due(db, settings(), monday + timedelta(days=4))
    assert {(await db.get(m.ImportRun, id)).job_name for id in ids} == {
        "sync-ipos",
        "sync-results-nse",
    }


async def test_waits_for_previous_job_then_runs_in_fifo_order(db, monkeypatch, tmp_path):
    from sqlalchemy import delete
    from apps.worker.market import acquire

    config(monkeypatch, tmp_path)
    await tracked(db, "LISTED")
    first = await create_run(db, "sync-prices-nse", "manual", {"trade_date": str(DAY)})
    second = await create_run(db, "sync-prices-bse", "manual", {"trade_date": str(DAY)})
    calls = []

    async def download(url):
        calls.append(url)
        return CSV.replace(b"NSE", b"BSE" if "bse" in url else b"NSE")

    assert await acquire(db, "existing-job")
    await db.commit()
    await run_pipeline(db, second, download)
    await run_pipeline(db, first, download)
    assert first.status == second.status == "QUEUED" and calls == []
    assert first.started_at is None and second.started_at is None
    assert first.error.startswith("WAITING_FOR_PREVIOUS_JOB")
    await db.execute(delete(m.JobLock).where(m.JobLock.owner == "existing-job"))
    await db.commit()
    # Even with the writer free, the later queued job cannot jump ahead.
    await run_pipeline(db, second, download)
    assert second.status == "QUEUED" and calls == []
    await run_pipeline(db, first, download)
    await run_pipeline(db, second, download)
    assert first.status == second.status == "SUCCESS"
    assert "nse" in calls[0] and "bse" in calls[1]
    assert first.error is None and second.error is None


async def test_queued_cancellation_does_not_execute(db, admin_client, monkeypatch, tmp_path):
    config(monkeypatch, tmp_path)
    run = await create_run(db, "sync-prices-nse", "manual", {"trade_date": str(DAY)})
    response = await admin_client.post(f"/api/v1/admin/market/runs/{run.id}/cancel")
    assert response.status_code == 200
    called = []

    async def download(url):
        called.append(url)
        return CSV

    await run_pipeline(db, run, download)
    assert run.status == "CANCELLED" and not called
    assert (
        await admin_client.post(f"/api/v1/admin/market/runs/{run.id}/cancel")
    ).status_code == 409

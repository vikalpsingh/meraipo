import json
from datetime import date

import httpx
import pytest

from apps.api.repository import journey
from apps.worker.exchange_pipeline import run_pipeline
from apps.worker.market import create_run
from packages.providers.ipoalerts import IPOAlerts
from packages.providers.market import FeedError
from packages.providers.nse_subscriptions import parse, url
from packages.shared.config import settings
from tests.test_ipoalerts import no_sleep, response, row


def payload():
    return {
        "updateTime": "Updated as on 25-Sep-2026 17:00:00",
        "dataList": [
            {
                "category": name,
                "noOfShareOffered": offered,
                "noOfSharesBid": bid,
                "noOfTotalMeant": multiple,
            }
            for name, offered, bid, multiple in [
                ("Qualified Institutional Buyers(QIBs)", "0", "0", "0.00"),
                ("Retail Individual Investors(RIIs)", "1,000", "2,500", "2.5"),
                ("Non Institutional Investors", "2,000", "0", "0"),
                ("Total", "3E3", "2.5E3", "0.833333333333"),
                ("Cut Off", "", "2500", ""),
            ]
        ],
    }


def test_categories_counts_timestamp_and_non_applicable_quota():
    _, records, _ = parse(json.dumps(payload()).encode(), "EXAMPLE", {"nse_symbol": "EXAMPLE"})
    value = records[0][1]
    assert value["source_timestamp"] == "2026-09-25T17:00:00+05:30"
    assert value["categories"]["qib"]["multiple"] is None
    assert value["categories"]["nii"]["multiple"] == "0.0000"
    assert value["categories"]["retail"]["multiple"] == "2.5000"
    assert value["categories"]["total"]["multiple"] == "0.8333"
    assert len(value["categories"]) == 4


@pytest.mark.parametrize("mutation", ["timestamp", "count", "duplicate", "symbol"])
def test_bad_snapshot_rejected(mutation):
    value = payload()
    if mutation == "timestamp":
        value["updateTime"] = "Updated as on null"
    elif mutation == "count":
        value["dataList"][1]["noOfSharesBid"] = "99999"
    elif mutation == "duplicate":
        value["dataList"].append(value["dataList"][1])
    else:
        value["symbol"] = "DIFFERENT"
    with pytest.raises(FeedError):
        parse(json.dumps(value).encode(), "EXAMPLE", {"nse_symbol": "EXAMPLE"})


async def test_new_vendor_ipo_categories_publish_together_and_repeat(db, monkeypatch):
    from packages.providers import ipo as registry

    monkeypatch.setattr(settings(), "ipo_data_provider", "ipoalerts")
    monkeypatch.setattr(settings(), "exchange_direct_enabled", True)
    monkeypatch.setattr(settings(), "nse_subscription_categories_enabled", True)
    monkeypatch.setattr("apps.worker.exchange_pipeline.india_today", lambda: date(2026, 9, 26))
    monkeypatch.setattr(
        registry,
        "get_ipo_provider",
        lambda config: IPOAlerts(
            "test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=response([row()] if request.url.params["status"] == "open" else [])
                )
            ),
            sleep=no_sleep,
        ),
    )

    async def download(target):
        assert target == url("FIXTURE")
        return json.dumps(payload()).encode()

    for _ in range(2):
        run = await create_run(db, "sync-ipos", "manual")
        await run_pipeline(db, run, download)
        assert run.status == "SUCCESS", run.counters
    value = await journey(db, "provider-fixture")
    assert value["subscription"]["multiple"] == 0.8333
    assert value["subscription"]["categories"]["retail"]["multiple"] == "2.5000"
    assert value["subscription"]["source_provider"] == "NSE_CONSOLIDATED"
    assert len(value["subscription_history"]) == 4

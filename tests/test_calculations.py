from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.api.schemas import IPOInput, MessageInput
from packages.shared.calculations import (
    business_trend,
    data_quality,
    financial_quarter,
    financial_year,
    margin,
    percent_change,
    valuation_label,
)
from packages.shared.config import Settings


@pytest.mark.parametrize(
    "value,baseline,expected",
    [
        (125, 100, Decimal(25)),
        (0, 100, Decimal(-100)),
        (None, 100, None),
        (100, None, None),
        (100, 0, None),
        (100, -20, None),
    ],
)
def test_returns(value, baseline, expected):
    assert percent_change(value, baseline) == expected


def test_margin_and_fiscal_boundaries():
    assert margin(10, 100) == 10
    assert margin(10, 0) is None
    assert (financial_year(date(2026, 3, 31)), financial_quarter(date(2026, 3, 31))) == (2026, 4)
    assert (financial_year(date(2026, 4, 1)), financial_quarter(date(2026, 4, 1))) == (2027, 1)


def test_trend_requires_comparable_data():
    assert business_trend({"revenue_yoy": 100}, {})["state"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize(
    "current,expected",
    [
        (dict(revenue_yoy=30, pat_yoy=40, margin=15), "IMPROVING"),
        (dict(revenue_yoy=5, pat_yoy=3, margin=5), "WEAKENING"),
        (dict(revenue_yoy=20, pat_yoy=20, margin=10), "STABLE"),
    ],
)
def test_business_trend(current, expected):
    assert business_trend(current, dict(revenue_yoy=20, pat_yoy=20, margin=10))["state"] == expected


def test_quality_precedence_and_staleness():
    assert data_quality(conflict=True, missing=True, verified=True) == "CONFLICT"
    assert data_quality(observed_at=datetime.now(timezone.utc) - timedelta(hours=25)) == "STALE"
    assert data_quality(missing=True, verified=True) == "PARTIAL"
    assert data_quality(verified=True) == "VERIFIED"


def test_validation_rejects_inverted_prices_and_html_links():
    with pytest.raises(ValueError):
        IPOInput(
            slug="test",
            name="Test",
            sector="Tech",
            status="OPEN",
            price_low=200,
            price_high=100,
            source_url="https://example.com",
        )
    with pytest.raises(ValueError):
        IPOInput(
            slug="test", name="Test", sector="Tech", status="OPEN", source_url="javascript:alert(1)"
        )


def test_message_schedule_and_production_settings():
    with pytest.raises(ValueError):
        MessageInput(
            title="Quote",
            content="Patience",
            active_from="2026-09-20T00:00:00Z",
            active_to="2026-09-19T00:00:00Z",
        )
    with pytest.raises(ValueError):
        Settings(environment="production", demo_mode=True)
    assert valuation_label(None, 20) == "Data unavailable"

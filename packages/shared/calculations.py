from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal


def percent_change(current, baseline):
    if current is None or baseline is None or baseline <= 0:
        return None
    return round((Decimal(str(current)) / Decimal(str(baseline)) - 1) * 100, 2)


def margin(ebitda, revenue):
    if ebitda is None or revenue is None or revenue <= 0:
        return None
    return round(Decimal(str(ebitda)) / Decimal(str(revenue)) * 100, 2)


def financial_year(day: date) -> int:
    return day.year + (1 if day.month >= 4 else 0)


def financial_quarter(day: date) -> int:
    return ((day.month - 4) % 12) // 3 + 1


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def data_quality(
    *, conflict=False, missing=False, verified=False, observed_at=None, ttl_hours=24, at=None
):
    if conflict:
        return "CONFLICT"
    if (
        observed_at
        and (utc(at or datetime.now(UTC)) - utc(observed_at)).total_seconds() > ttl_hours * 3600
    ):
        return "STALE"
    if missing:
        return "PARTIAL"
    return "VERIFIED" if verified else "UNVERIFIED"


@dataclass(frozen=True)
class TrendPolicy:
    weights: dict[str, int] = field(
        default_factory=lambda: {
            "revenue": 25,
            "pat": 25,
            "margin": 20,
            "roce": 10,
            "debt": 10,
            "cash": 10,
        }
    )
    improving: int = 30
    weakening: int = -30
    version: str = "1"


def business_trend(current: dict, previous: dict, policy: TrendPolicy | None = None) -> dict:
    policy = policy or TrendPolicy()
    mandatory = [current.get(k) for k in ("revenue_yoy", "pat_yoy", "margin")] + [
        previous.get(k) for k in ("revenue_yoy", "pat_yoy", "margin")
    ]
    if any(value is None for value in mandatory):
        return {
            "state": "INSUFFICIENT_DATA",
            "score": None,
            "version": policy.version,
            "reason": "Two comparable YoY results and EBITDA margins are required.",
        }
    signs = {}
    for label, key in (
        ("revenue", "revenue_yoy"),
        ("pat", "pat_yoy"),
        ("margin", "margin"),
        ("roce", "roce"),
        ("debt", "debt"),
    ):
        a, b = current.get(key), previous.get(key)
        if a is not None and b is not None:
            delta = float(a) - float(b)
            if label == "debt":
                delta = -delta
            signs[label] = 1 if delta > 0.5 else -1 if delta < -0.5 else 0
    if current.get("cfo") is not None and current.get("pat") is not None and current["pat"] > 0:
        signs["cash"] = 1 if current["cfo"] >= current["pat"] else -1 if current["cfo"] < 0 else 0
    total = sum(policy.weights[k] for k in signs)
    score = (
        round(sum(policy.weights[k] * v for k, v in signs.items()) / total * 100, 2) if total else 0
    )
    state = (
        "IMPROVING"
        if score >= policy.improving
        else "WEAKENING" if score <= policy.weakening else "STABLE"
    )
    return {
        "state": state,
        "score": score,
        "version": policy.version,
        "reason": "Weighted change in reported business metrics; not a recommendation.",
    }


def valuation_label(pe, peer):
    if pe is None or peer is None or pe <= 0 or peer <= 0:
        return "Data unavailable"
    ratio = pe / peer
    return (
        "Above peer median"
        if ratio > 1.1
        else "Below peer median" if ratio < 0.9 else "Near peer median"
    )

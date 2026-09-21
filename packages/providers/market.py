"""Versioned, licensed JSON feed boundary. No website scraping or browser cookies."""

import asyncio
import calendar
import hashlib
import json
import random
from datetime import UTC, date, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import Field, TypeAdapter, field_validator, model_validator

from apps.api.schemas import Input, IPOInput, Metrics, https_url

VERSION = "meraipo-feed-v1"
CATEGORIES = ("qib", "nii", "bnii", "snii", "retail", "employee", "shareholder", "total")


class FeedError(Exception):
    def __init__(self, code, raw=None):
        super().__init__(code)
        self.raw = raw


class FeedConfig(Input):
    url: str
    token: str = ""
    enabled: bool = False
    authority: Literal["NSE", "BSE", "LICENSED", "UNOFFICIAL"]
    xbrl_concepts: dict[str, str] = Field(default_factory=dict)
    _url = field_validator("url")(https_url)

    @field_validator("url")
    @classmethod
    def no_query_secret(cls, value):
        if urlsplit(value).query or urlsplit(value).fragment:
            raise ValueError("Use Authorization header for credentials, not URL parameters")
        return value


def configuration(value):
    data = TypeAdapter(dict[str, dict[str, FeedConfig]]).validate_json(value or "{}")
    if set(data) - {"ipos", "subscriptions", "gmp", "prices", "results"}:
        raise ValueError("Unknown feed kind")
    for kind, feeds in data.items():
        for name, feed in feeds.items():
            if len(name) > 100:
                raise ValueError("Provider name too long")
            if kind in ("ipos", "subscriptions", "results") and feed.authority not in (
                "NSE",
                "BSE",
            ):
                raise ValueError("Official exchange provenance required")
            if kind == "gmp" and feed.authority != "UNOFFICIAL":
                raise ValueError("GMP must be labelled unofficial")
    return data


class Identity(Input):
    isin: str | None = Field(None, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    nse_symbol: str | None = Field(None, min_length=1, max_length=40)
    bse_code: str | None = Field(None, pattern=r"^[0-9]{6}$")
    bse_symbol: str | None = Field(None, pattern=r"^[A-Z0-9&._-]{1,40}$")
    bse_issue_id: str | None = Field(None, pattern=r"^[0-9]{1,12}$")

    @model_validator(mode="after")
    def identity_required(self):
        if not any((self.isin, self.nse_symbol, self.bse_code, self.bse_symbol, self.bse_issue_id)):
            raise ValueError("ISIN or exchange identifier required; names are not identifiers")
        return self

    def exchange_identifiers(self):
        return (
            ("NSE", self.nse_symbol),
            ("BSE", self.bse_code),
            ("BSE_SYMBOL", self.bse_symbol),
            ("BSE_ISSUE", self.bse_issue_id),
        )


class Observation(Identity):
    source_url: str
    source_timestamp: datetime
    _url = field_validator("source_url")(https_url)

    @field_validator("source_timestamp")
    @classmethod
    def aware(cls, value):
        if not value.tzinfo or value > datetime.now(UTC):
            raise ValueError("An explicit, non-future timestamp is required")
        return value


class Issue(Observation):
    company_type: Literal["GENERAL", "BANK", "NBFC", "INSURANCE", "REIT", "INVIT", "OTHER"] = (
        "GENERAL"
    )
    official_status: str = Field(max_length=40)
    issue: IPOInput
    registrar: str | None = Field(None, max_length=200)
    lead_managers: list[str] | None = Field(None, max_length=20)
    retail_quota_pct: Decimal | None = Field(None, ge=0, le=100, decimal_places=4)
    qib_quota_pct: Decimal | None = Field(None, ge=0, le=100, decimal_places=4)
    nii_quota_pct: Decimal | None = Field(None, ge=0, le=100, decimal_places=4)
    employee_quota_pct: Decimal | None = Field(None, ge=0, le=100, decimal_places=4)
    shareholder_quota_pct: Decimal | None = Field(None, ge=0, le=100, decimal_places=4)
    anchor_date: date | None = None
    allotment_date: date | None = None
    refund_date: date | None = None
    demat_credit_date: date | None = None


class SubscriptionCategory(Input):
    multiple: Decimal | None = Field(None, ge=0, max_digits=20, decimal_places=4)
    bid_shares: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=0)
    offered_shares: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=0)

    @model_validator(mode="after")
    def ratio(self):
        if self.bid_shares is not None and self.offered_shares is not None:
            if self.offered_shares == 0:
                if self.multiple is not None:
                    raise ValueError("No subscription multiple for zero offered shares")
            else:
                calculated = self.bid_shares / self.offered_shares
                if self.multiple is not None and abs(self.multiple - calculated) > Decimal("0.01"):
                    raise ValueError("Subscription multiple disagrees with share counts")
                self.multiple = calculated.quantize(Decimal("0.0001"))
        return self


class Subscriptions(Observation):
    categories: dict[str, SubscriptionCategory]

    @field_validator("categories")
    @classmethod
    def category_names(cls, value):
        if not value or set(value) - set(CATEGORIES):
            raise ValueError("Unknown or empty subscription categories")
        return value


class Premium(Observation):
    value: Decimal = Field(max_digits=20, decimal_places=4)


class Eod(Observation):
    price_date: date
    close: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    open: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    high: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    low: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    previous_close: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    volume: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=0)
    turnover: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=4)

    @model_validator(mode="after")
    def coherent(self):
        if self.price_date > date.today():
            raise ValueError("Future trading date")
        for value in (self.open, self.close):
            if value is not None and (
                (self.high is not None and value > self.high)
                or (self.low is not None and value < self.low)
            ):
                raise ValueError("Price outside high/low")
        return self


class Financial(Observation, Metrics):
    financial_year: int = Field(ge=2000, le=2100)
    quarter: int | None = Field(None, ge=1, le=4)
    period_type: Literal["QUARTERLY", "ANNUAL"]
    statement_type: Literal["CONSOLIDATED", "STANDALONE"]
    period_start: date
    period_end: date
    filing_id: str = Field(min_length=1, max_length=200)
    currency: Literal["INR"] = "INR"
    unit: Literal["INR_CRORE"] = "INR_CRORE"
    industry_metrics: dict[str, Decimal | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def period_and_metrics(self):
        if self.period_end > date.today() or self.period_start >= self.period_end:
            raise ValueError("Invalid financial period")
        year = self.period_end.year + (self.period_end.month > 3)
        quarter = (self.period_end.month - 4) % 12 // 3 + 1
        if self.financial_year != year or self.period_end.month not in (3, 6, 9, 12):
            raise ValueError("Financial year uses Indian March year-end")
        days = (self.period_end - self.period_start).days + 1
        if self.period_type == "QUARTERLY" and (self.quarter != quarter or not 89 <= days <= 92):
            raise ValueError("Use discrete quarters, not year-to-date results")
        if self.period_type == "ANNUAL" and (self.quarter is not None or not 365 <= days <= 366):
            raise ValueError("Annual result must span a full financial year")
        expected_start = (
            date(self.financial_year - 1, 4, 1)
            if self.period_type == "ANNUAL"
            else date(self.period_end.year, self.period_end.month - 2, 1)
        )
        expected_end = (
            date(self.financial_year, 3, 31)
            if self.period_type == "ANNUAL"
            else date(
                self.period_end.year,
                self.period_end.month,
                calendar.monthrange(self.period_end.year, self.period_end.month)[1],
            )
        )
        if self.period_start != expected_start or self.period_end != expected_end:
            raise ValueError("Reporting dates must match a complete Indian fiscal period")
        allowed = {
            "other_income",
            "total_income",
            "finance_cost",
            "depreciation",
            "pbt",
            "tax",
            "net_interest_income",
            "operating_profit",
            "aum",
            "gnpa",
            "nnpa",
        }
        if set(self.industry_metrics) - allowed:
            raise ValueError("Unknown industry metric")
        return self


MODELS = {
    "ipos": Issue,
    "subscriptions": Subscriptions,
    "gmp": Premium,
    "prices": Eod,
    "results": Financial,
}


def normalize_record(kind, value, config):
    if kind == "results" and isinstance(value, dict) and "xbrl" in value:
        from packages.providers.xbrl import parse_instance

        value = dict(value)
        if not config.xbrl_concepts:
            raise FeedError("XBRL_TAXONOMY_NOT_CONFIGURED")
        parsed = parse_instance(
            value.pop("xbrl"),
            value.pop("context_id"),
            config.xbrl_concepts,
            value["statement_type"],
        )
        value.update(period_start=parsed["period_start"], period_end=parsed["period_end"])
        value["industry_metrics"] = dict(value.get("industry_metrics", {}))
        for key, metric in parsed["metrics"].items():
            if key in Metrics.model_fields:
                value[key] = metric
            else:
                value["industry_metrics"][key] = metric
    return MODELS[kind].model_validate(value)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def safe_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


async def fetch_feed(config, params, transport=None, sleep=asyncio.sleep):
    """Bounded bulk request. Credentials never enter URLs, stored payload metadata or errors."""
    headers = {
        "User-Agent": "MeraIPO/1.0",
        "X-Request-ID": str(uuid4()),
        "Accept": "application/json",
    }
    if config.token:
        headers["Authorization"] = "Bearer " + config.token
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=transport) as client:
        for attempt in range(4):
            retry_after = None
            try:
                async with client.stream(
                    "GET", config.url, params=params, headers=headers
                ) as response:
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        retry_after = response.headers.get("Retry-After")
                        raise httpx.TransportError("Retryable upstream status")
                    if response.status_code != 200:
                        raise FeedError(f"HTTP_{response.status_code}")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 5_000_000:
                            raise FeedError("PAYLOAD_TOO_LARGE")
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode("utf-8")
                try:
                    body = json.loads(raw)
                    if (
                        body.get("schema") != VERSION
                        or not isinstance(body.get("records"), list)
                        or len(body["records"]) > 5000
                    ):
                        raise ValueError()
                except (ValueError, AttributeError) as exc:
                    raise FeedError("INVALID_FEED_SCHEMA", raw=raw) from exc
                return raw, body["records"]
            except httpx.TransportError:
                if attempt == 3:
                    raise FeedError("UPSTREAM_UNAVAILABLE") from None
                delay = (2, 5, 15)[attempt] + random.random()
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(
                                delay,
                                (
                                    parsedate_to_datetime(retry_after) - datetime.now(UTC)
                                ).total_seconds(),
                            )
                        except (ValueError, TypeError):
                            pass
                    if delay > 30:
                        raise FeedError("RATE_LIMITED_RETRY_LATER") from None
                await sleep(delay)

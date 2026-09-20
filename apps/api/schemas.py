from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


def https_url(value):
    from urllib.parse import urlparse

    if value is not None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("A public HTTPS URL without credentials is required")
    return value


class Metrics(Input):
    revenue: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=4)
    ebitda: Decimal | None = Field(None, max_digits=24, decimal_places=4)
    pat: Decimal | None = Field(None, max_digits=24, decimal_places=4)
    eps: Decimal | None = Field(None, max_digits=20, decimal_places=4)
    debt: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=4)
    cfo: Decimal | None = Field(None, max_digits=24, decimal_places=4)
    roe: Decimal | None = Field(None, max_digits=12, decimal_places=4)
    roce: Decimal | None = Field(None, max_digits=12, decimal_places=4)


class ProvenanceInput(Input):
    source_url: str = Field(max_length=2000)
    provider: str = Field(default="manual", min_length=1, max_length=120)
    source_timestamp: datetime | None = None
    verification_status: Literal["VERIFIED", "UNVERIFIED", "PARTIAL"] = "UNVERIFIED"
    _url = field_validator("source_url")(https_url)


class IPOInput(ProvenanceInput):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    name: str = Field(min_length=2, max_length=200)
    sector: str = Field(min_length=1, max_length=120)
    board: Literal["Mainboard", "SME"] = "Mainboard"
    ticker: str | None = Field(None, max_length=40)
    exchange: Literal["NSE", "BSE"] = "NSE"
    status: Literal["OPEN", "UPCOMING", "CLOSED", "LISTED"]
    open_date: date | None = None
    close_date: date | None = None
    listing_date: date | None = None
    price_low: Decimal | None = Field(None, gt=0)
    price_high: Decimal | None = Field(None, gt=0)
    issue_price: Decimal | None = Field(None, gt=0)
    listing_price: Decimal | None = Field(None, gt=0)
    lot_size: int | None = Field(None, gt=0, le=1000000)
    issue_size: Decimal | None = Field(None, ge=0)
    fresh_issue: Decimal | None = Field(None, ge=0)
    ofs: Decimal | None = Field(None, ge=0)
    screener_url: str | None = Field(None, max_length=2000)
    exchange_url: str | None = Field(None, max_length=2000)
    rhp_url: str | None = Field(None, max_length=2000)
    baseline: Metrics | None = None
    baseline_pe: Decimal | None = None
    baseline_market_cap: Decimal | None = Field(None, ge=0)
    _links = field_validator("screener_url", "exchange_url", "rhp_url")(https_url)

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.price_low is not None
            and self.price_high is not None
            and self.price_low > self.price_high
        ):
            raise ValueError("Lower price must not exceed upper price")
        if self.open_date and self.close_date and self.open_date > self.close_date:
            raise ValueError("Open date must precede close date")
        if self.close_date and self.listing_date and self.close_date > self.listing_date:
            raise ValueError("Listing must follow issue close")
        return self


class QuarterInput(Metrics, ProvenanceInput):
    financial_year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=1, le=4)
    import_key: str = Field(min_length=8, max_length=200)


class ApplicantGuideInput(ProvenanceInput):
    category: str = Field(min_length=2, max_length=100)
    min_lots: int | None = Field(None, ge=1, le=1000000)
    max_lots: int | None = Field(None, ge=1, le=1000000)
    max_amount: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    bid_deadline: datetime | None = None
    mandate_deadline: datetime | None = None
    allotment_date: date | None = None
    unblock_date: date | None = None
    schedule_status: Literal["TENTATIVE", "CONFIRMED"] = "TENTATIVE"
    registrar_name: str | None = Field(None, min_length=2, max_length=160)
    registrar_url: str | None = Field(None, max_length=2000)
    business_summary: str | None = Field(None, max_length=800)
    strengths: str | None = Field(None, max_length=1200)
    risks: str | None = Field(None, max_length=1200)
    proceeds: str | None = Field(None, max_length=800)
    reviewed_on: date
    _registrar = field_validator("registrar_url")(https_url)

    @model_validator(mode="after")
    def coherent_guide(self):
        if self.reviewed_on > date.today():
            raise ValueError("Review date cannot be in the future")
        if self.max_lots and (not self.min_lots or self.max_lots < self.min_lots):
            raise ValueError("Maximum lots must be at least the minimum")
        for deadline in (self.bid_deadline, self.mandate_deadline):
            if deadline and not deadline.tzinfo:
                raise ValueError("Deadlines require an explicit timezone")
        if (
            self.bid_deadline
            and self.mandate_deadline
            and self.mandate_deadline < self.bid_deadline
        ):
            raise ValueError("Mandate deadline must not precede bidding deadline")
        if self.allotment_date and self.unblock_date and self.unblock_date < self.allotment_date:
            raise ValueError("Unblocking initiation cannot precede allotment")
        if bool(self.registrar_name) != bool(self.registrar_url):
            raise ValueError("Registrar name and URL must be supplied together")
        for points in (self.strengths, self.risks):
            if points and len([line for line in points.splitlines() if line.strip()]) > 3:
                raise ValueError("Use at most three points, one per line")
        return self


class GMPInput(ProvenanceInput):
    value: Decimal | None = None
    observed_at: datetime
    import_key: str = Field(min_length=8, max_length=200)

    @field_validator("observed_at")
    @classmethod
    def timestamp(cls, value):
        if not value.tzinfo or value > datetime.now(UTC):
            raise ValueError("GMP timestamp must have a timezone and cannot be in the future")
        return value


class MessageInput(Input):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=2000)
    attribution: str | None = Field(None, max_length=160)
    kind: Literal["quote", "message"] = "quote"
    enabled: bool = True
    active_from: datetime | None = None
    active_to: datetime | None = None

    @model_validator(mode="after")
    def schedule(self):
        for value in (self.active_from, self.active_to):
            if value and not value.tzinfo:
                raise ValueError("Schedule needs a timezone")
        if self.active_from and self.active_to and self.active_to <= self.active_from:
            raise ValueError("End must be after start")
        return self


class AdInput(Input):
    text: str = Field(min_length=1, max_length=240)
    image_url: str | None = Field(None, max_length=2000)
    destination_url: str = Field(max_length=2000)
    placement: Literal["home", "tracker"] = "home"
    enabled: bool = False
    _links = field_validator("image_url", "destination_url")(https_url)


class LoginInput(Input):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PriceInput(ProvenanceInput):
    price_date: date
    close: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    high: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)
    low: Decimal | None = Field(None, gt=0, max_digits=20, decimal_places=4)

    @model_validator(mode="after")
    def price_range(self):
        if self.price_date > date.today():
            raise ValueError("EOD price date cannot be in the future")
        if (
            self.high is not None
            and self.high < self.close
            or self.low is not None
            and self.low > self.close
        ):
            raise ValueError("Close must lie within the reported daily range")
        return self


class DocumentInput(ProvenanceInput):
    kind: Literal["DRHP", "RHP", "PROSPECTUS", "RESULTS"]

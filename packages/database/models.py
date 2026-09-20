from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Sector(Entity, Base):
    __tablename__ = "sectors"
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Company(Entity, Base):
    __tablename__ = "companies"
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    sector_id: Mapped[str | None] = mapped_column(ForeignKey("sectors.id"), index=True)
    board: Mapped[str] = mapped_column(String(20), default="Mainboard")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    screener_url: Mapped[str | None] = mapped_column(Text)
    exchange_url: Mapped[str | None] = mapped_column(Text)
    company_type: Mapped[str] = mapped_column(
        String(20), default="GENERAL", server_default="GENERAL"
    )
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)


class Identifier(Entity, Base):
    __tablename__ = "company_identifiers"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(40))
    exchange: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("ticker", "exchange"),)


class IPO(Entity, Base):
    __tablename__ = "ipos"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), unique=True)
    status: Mapped[str] = mapped_column(String(25), index=True)
    price_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    issue_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    listing_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    lot_size: Mapped[int | None] = mapped_column(Integer)
    issue_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    fresh_issue: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    ofs: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    quality: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    raw_status: Mapped[str | None] = mapped_column(String(40))
    lifecycle: Mapped[str | None] = mapped_column(String(30))
    source_provider: Mapped[str | None] = mapped_column(String(100))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registrar: Mapped[str | None] = mapped_column(String(200))
    lead_managers: Mapped[list | None] = mapped_column(JSON)
    retail_quota_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    qib_quota_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    nii_quota_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    employee_quota_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    shareholder_quota_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))


class IPODate(Entity, Base):
    __tablename__ = "ipo_dates"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), unique=True)
    open_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)
    listing_date: Mapped[date | None] = mapped_column(Date, index=True)
    anchor_date: Mapped[date | None] = mapped_column(Date)
    allotment_date: Mapped[date | None] = mapped_column(Date)
    refund_date: Mapped[date | None] = mapped_column(Date)
    demat_credit_date: Mapped[date | None] = mapped_column(Date)


class Source(Entity, Base):
    __tablename__ = "data_sources"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(30), default="manual")


class ApplicantGuide(Entity, Base):
    __tablename__ = "ipo_applicant_guides"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), unique=True)
    category: Mapped[str] = mapped_column(String(100))
    min_lots: Mapped[int | None] = mapped_column(Integer)
    max_lots: Mapped[int | None] = mapped_column(Integer)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    bid_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mandate_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allotment_date: Mapped[date | None] = mapped_column(Date)
    unblock_date: Mapped[date | None] = mapped_column(Date)
    schedule_status: Mapped[str] = mapped_column(String(20))
    registrar_name: Mapped[str | None] = mapped_column(String(160))
    registrar_url: Mapped[str | None] = mapped_column(Text)
    business_summary: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    proceeds: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    reviewed_on: Mapped[date] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(String(20))


class Provenance(Entity, Base):
    __tablename__ = "field_provenance"
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    field_name: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    source_url: Mapped[str] = mapped_column(Text)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")


class Document(Entity, Base):
    __tablename__ = "ipo_documents"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)


class Subscription(Entity, Base):
    __tablename__ = "ipo_subscriptions"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), index=True)
    multiple: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    categories: Mapped[dict | None] = mapped_column(JSON)
    source_provider: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("data_raw_payloads.id"))


class GMP(Entity, Base):
    __tablename__ = "ipo_gmp_history"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), index=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    import_key: Mapped[str] = mapped_column(String(200), unique=True)
    source_provider: Mapped[str | None] = mapped_column(String(100))
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("data_raw_payloads.id"))


class SubscriptionDay(Entity, Base):
    __tablename__ = "company_subscription_days"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    subscription_date: Mapped[date] = mapped_column(Date)
    exchange: Mapped[str] = mapped_column(String(20))
    subscription_id: Mapped[str] = mapped_column(ForeignKey("ipo_subscriptions.id"))
    __table_args__ = (UniqueConstraint("company_id", "subscription_date", "exchange"),)


class SubscriptionDetail(Entity, Base):
    __tablename__ = "company_subscription_details"
    day_id: Mapped[str] = mapped_column(ForeignKey("company_subscription_days.id"))
    category: Mapped[str] = mapped_column(String(20))
    multiple: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    bid_shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    offered_shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    __table_args__ = (UniqueConstraint("day_id", "category"),)


class MarketStage(Entity, Base):
    __tablename__ = "market_staging"
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(100))
    authority: Mapped[str] = mapped_column(String(20))
    raw_payload_id: Mapped[str] = mapped_column(ForeignKey("data_raw_payloads.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    error: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_stage_pending", "status", "kind", "created_at"),)


class ExchangePrice(Entity, Base):
    __tablename__ = "exchange_price_history"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    price_date: Mapped[date] = mapped_column(Date)
    exchange: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    raw_payload_id: Mapped[str] = mapped_column(ForeignKey("data_raw_payloads.id"))
    __table_args__ = (UniqueConstraint("company_id", "price_date", "exchange"),)


class FinancialMetrics:
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    ebitda: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    pat: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    debt: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    cfo: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    roce: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class Baseline(Entity, FinancialMetrics, Base):
    __tablename__ = "ipo_baseline_financials"
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"), unique=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    pe: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))


class Period(Entity, Base):
    __tablename__ = "financial_periods"
    financial_year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("financial_year", "quarter"),)


class FilingMetadata:
    statement_type: Mapped[str] = mapped_column(
        String(20), default="STANDALONE", server_default="STANDALONE"
    )
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    source_provider: Mapped[str | None] = mapped_column(String(100))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filing_id: Mapped[str | None] = mapped_column(String(200))
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("data_raw_payloads.id"))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(40))
    industry_metrics: Mapped[dict | None] = mapped_column(JSON)


class Quarterly(Entity, FinancialMetrics, FilingMetadata, Base):
    __tablename__ = "quarterly_financials"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    period_id: Mapped[str] = mapped_column(ForeignKey("financial_periods.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_url: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    import_key: Mapped[str] = mapped_column(String(200), unique=True)
    __table_args__ = (UniqueConstraint("company_id", "period_id", "revision"),)


class Annual(Entity, FinancialMetrics, FilingMetadata, Base):
    __tablename__ = "annual_financials"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    financial_year: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    source_url: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("company_id", "financial_year", "revision", name="uq_annual_revision"),
    )


class Price(Entity, Base):
    __tablename__ = "market_prices_eod"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    price_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    source_url: Mapped[str] = mapped_column(Text)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    source_provider: Mapped[str | None] = mapped_column(String(100))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload_id: Mapped[str | None] = mapped_column(ForeignKey("data_raw_payloads.id"))
    __table_args__ = (UniqueConstraint("company_id", "price_date"),)


class PriceSnapshot(Entity, Base):
    __tablename__ = "company_price_snapshots"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), unique=True)
    cmp: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    ath: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    high_52w: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    low_52w: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    price_date: Mapped[date | None] = mapped_column(Date)


class Peer(Entity, Base):
    __tablename__ = "peer_companies"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    peer_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    __table_args__ = (UniqueConstraint("company_id", "peer_id"),)


class Valuation(Entity, Base):
    __tablename__ = "valuation_snapshots"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    pe: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    peer_median_pe: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    ev_ebitda: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    __table_args__ = (UniqueConstraint("company_id", "as_of"),)


class Trend(Entity, Base):
    __tablename__ = "business_trend_snapshots"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    state: Mapped[str] = mapped_column(String(30), index=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    methodology_version: Mapped[str] = mapped_column(String(30), default="1")


class ImportRun(Entity, Base):
    __tablename__ = "data_import_runs"
    key: Mapped[str] = mapped_column(String(200), unique=True)
    provider: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(100))
    job_name: Mapped[str | None] = mapped_column(String(40), index=True)
    trigger: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict | None] = mapped_column(JSON)
    parameters: Mapped[dict | None] = mapped_column(JSON)


class RawPayload(Entity, Base):
    __tablename__ = "data_raw_payloads"
    provider: Mapped[str] = mapped_column(String(100))
    data_type: Mapped[str] = mapped_column(String(40))
    requested_url: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int] = mapped_column(Integer)
    payload_text: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(40))


class JobLock(Base):
    __tablename__ = "job_locks"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SchedulerControl(Base):
    __tablename__ = "scheduler_controls"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)


class JobError(Entity, Base):
    __tablename__ = "ingestion_job_errors"
    run_id: Mapped[str] = mapped_column(ForeignKey("data_import_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    item: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text)


class QualityIssue(Entity, Base):
    __tablename__ = "data_quality_issues"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class SiteMessage(Entity, Base):
    __tablename__ = "site_messages"
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20), default="quote")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Advertisement(Entity, Base):
    __tablename__ = "advertisements"
    text: Mapped[str] = mapped_column(String(240))
    image_url: Mapped[str | None] = mapped_column(Text)
    destination_url: Mapped[str] = mapped_column(Text)
    placement: Mapped[str] = mapped_column(String(30), default="home")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminUser(Entity, Base):
    __tablename__ = "admin_users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminSession(Entity, Base):
    __tablename__ = "admin_sessions"
    admin_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Audit(Entity, Base):
    __tablename__ = "audit_logs"
    admin_id: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id"))
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    changes: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)


class FutureUser(Entity, Base):
    __tablename__ = "future_users"
    email: Mapped[str] = mapped_column(String(254), unique=True)


class FutureApplication(Entity, Base):
    __tablename__ = "future_ipo_applications"
    user_id: Mapped[str] = mapped_column(ForeignKey("future_users.id"))
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.id"))
    __table_args__ = (UniqueConstraint("user_id", "ipo_id"),)


Index(
    "ix_provenance_entity_field",
    Provenance.entity_type,
    Provenance.entity_id,
    Provenance.field_name,
)
Index("ix_subscription_ipo_observed", Subscription.ipo_id, Subscription.observed_at)

"""Separate collection from publication; relational daily subscription details."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_exchange_pipeline"
down_revision = "626a25f2c463"
branch_labels = None
depends_on = None


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "exchange_price_history",
        *entity(),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "raw_payload_id", sa.String(36), sa.ForeignKey("data_raw_payloads.id"), nullable=False
        ),
        sa.UniqueConstraint("company_id", "price_date", "exchange"),
    )
    op.create_table(
        "market_staging",
        *entity(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("authority", sa.String(20), nullable=False),
        sa.Column(
            "raw_payload_id", sa.String(36), sa.ForeignKey("data_raw_payloads.id"), nullable=False
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(100)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_stage_pending", "market_staging", ["status", "kind", "created_at"])
    op.create_table(
        "company_subscription_days",
        *entity(),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("subscription_date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column(
            "subscription_id", sa.String(36), sa.ForeignKey("ipo_subscriptions.id"), nullable=False
        ),
        sa.UniqueConstraint("company_id", "subscription_date", "exchange"),
    )
    op.create_table(
        "company_subscription_details",
        *entity(),
        sa.Column(
            "day_id", sa.String(36), sa.ForeignKey("company_subscription_days.id"), nullable=False
        ),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("multiple", sa.Numeric(20, 4)),
        sa.Column("bid_shares", sa.Numeric(24, 0)),
        sa.Column("offered_shares", sa.Numeric(24, 0)),
        sa.UniqueConstraint("day_id", "category"),
    )


def downgrade():
    op.drop_table("exchange_price_history")
    op.drop_table("company_subscription_details")
    op.drop_table("company_subscription_days")
    op.drop_table("market_staging")

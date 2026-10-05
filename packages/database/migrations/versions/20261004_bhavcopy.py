"""Durable bhavcopy imports and exchange-specific numeric daily closes."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_bhavcopy"
down_revision = "20261003_click_analytics"
branch_labels = None
depends_on = None


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.add_column("company_price_snapshots", sa.Column("closing_exchange", sa.String(3)))
    op.add_column("company_price_snapshots", sa.Column("previous_close", sa.Numeric(20, 4)))
    op.create_table(
        "bhavcopy_files",
        *entity(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("data_import_runs.id")),
        sa.Column("exchange", sa.String(3), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64)),
        sa.Column("path", sa.Text()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("counters", sa.JSON()),
        sa.Column("errors", sa.JSON()),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_bhavcopy_session", "bhavcopy_files", ["exchange", "trade_date", "created_at"]
    )
    op.create_table(
        "equity_daily_closes",
        *entity(),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("exchange", sa.String(3), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        *[
            sa.Column(k, sa.Numeric(20, 4), nullable=k != "close")
            for k in ("close", "open", "high", "low", "previous_close")
        ],
        sa.Column("volume", sa.Numeric(24, 0)),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("bhavcopy_files.id"), nullable=False),
        sa.Column("security_id", sa.String(40), nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column("series", sa.String(10), nullable=False),
        sa.UniqueConstraint("company_id", "exchange", "trade_date", name="uq_equity_close"),
    )
    op.create_table(
        "equity_close_revisions",
        *entity(),
        sa.Column(
            "close_id", sa.String(36), sa.ForeignKey("equity_daily_closes.id"), nullable=False
        ),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("bhavcopy_files.id"), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
    )
    op.create_index("ix_equity_close_revisions_close_id", "equity_close_revisions", ["close_id"])


def downgrade():
    op.drop_table("equity_close_revisions")
    op.drop_table("equity_daily_closes")
    op.drop_table("bhavcopy_files")
    op.drop_column("company_price_snapshots", "previous_close")
    op.drop_column("company_price_snapshots", "closing_exchange")

"""Persistent source filings, originals, checkpoints and normalized revisions."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_results"
down_revision = "20261004_bhavcopy_retry"
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
        "result_sources",
        sa.Column("exchange", sa.String(3), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule", sa.String(5), nullable=False),
        sa.Column("status", sa.String(80), nullable=False),
        sa.Column("last_success", sa.DateTime(timezone=True)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "result_filings",
        *entity(),
        sa.Column("exchange", sa.String(3), nullable=False),
        sa.Column("identity", sa.String(64), nullable=False, unique=True),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id")),
        sa.Column("identifier", sa.String(40), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(80), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_result_filings_exchange", "result_filings", ["exchange"])
    op.create_index("ix_result_filings_company_id", "result_filings", ["company_id"])
    op.create_table(
        "result_attachments",
        *entity(),
        sa.Column("filing_id", sa.String(36), sa.ForeignKey("result_filings.id"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.UniqueConstraint("filing_id", "checksum"),
    )
    op.create_index("ix_result_attachments_filing_id", "result_attachments", ["filing_id"])
    op.create_table(
        "financial_results",
        *entity(),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("filing_id", sa.String(36), sa.ForeignKey("result_filings.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "period_start", "period_end", "period_type", "basis", "revision"
        ),
    )
    op.create_index("ix_financial_results_company_id", "financial_results", ["company_id"])


def downgrade():
    for table in ("financial_results", "result_attachments", "result_filings", "result_sources"):
        op.drop_table(table)

"""Durable source Retry-After and per-company historical coverage."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_result_retry"
down_revision = "20261005_results"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("result_sources", sa.Column("retry_at", sa.DateTime(timezone=True)))
    op.create_table(
        "result_history_checkpoints",
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), primary_key=True),
        sa.Column("exchange", sa.String(3), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
    )


def downgrade():
    op.drop_table("result_history_checkpoints")
    op.drop_column("result_sources", "retry_at")

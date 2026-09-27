"""Provider-neutral IPO enrichment; existing masters and identifiers are preserved."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_ipo_provider"
down_revision = "20260921_customer_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ipo_provider_details",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ipo_id", sa.String(36), sa.ForeignKey("ipos.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_id", sa.String(36), sa.ForeignKey("data_raw_payloads.id")),
    )


def downgrade():
    op.drop_table("ipo_provider_details")

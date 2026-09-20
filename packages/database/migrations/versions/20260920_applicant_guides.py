"""Issue-specific applicant guidance, dates and editorial summaries."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_applicant_guides"
down_revision = "98017c9d7309"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ipo_applicant_guides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ipo_id", sa.String(36), sa.ForeignKey("ipos.id"), nullable=False, unique=True),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("min_lots", sa.Integer()),
        sa.Column("max_lots", sa.Integer()),
        sa.Column("max_amount", sa.Numeric(20, 4)),
        sa.Column("bid_deadline", sa.DateTime(timezone=True)),
        sa.Column("mandate_deadline", sa.DateTime(timezone=True)),
        sa.Column("allotment_date", sa.Date()),
        sa.Column("unblock_date", sa.Date()),
        sa.Column("schedule_status", sa.String(20), nullable=False),
        sa.Column("registrar_name", sa.String(160)),
        sa.Column("registrar_url", sa.Text()),
        sa.Column("business_summary", sa.Text()),
        sa.Column("strengths", sa.Text()),
        sa.Column("risks", sa.Text()),
        sa.Column("proceeds", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
    )


def downgrade():
    op.drop_table("ipo_applicant_guides")

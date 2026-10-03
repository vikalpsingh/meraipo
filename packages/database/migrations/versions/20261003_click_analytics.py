"""Bounded daily click aggregates; no individual event records."""

import sqlalchemy as sa
from alembic import op

revision = "20261003_click_analytics"
down_revision = "20261002_market_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analytics_click_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("section", sa.String(20), primary_key=True),
        sa.Column("clicks", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("analytics_click_daily")

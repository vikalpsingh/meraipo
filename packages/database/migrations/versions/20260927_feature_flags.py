"""Persistent, default-off public feature releases."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_feature_flags"
down_revision = "20260921_ipo_provider"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_feature_flags",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("site_feature_flags")

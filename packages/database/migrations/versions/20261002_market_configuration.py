"""Store administrator-managed market provider configuration."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_market_config"
down_revision = "20261002_ad_logo_cache"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_configuration",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("ipoalerts_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("market_feeds_json_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("admin_users.id"), nullable=True),
    )


def downgrade():
    op.drop_table("market_configuration")

"""Preserve exchange provenance on existing subscription installations."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_subscription_source"
down_revision = "20260920_exchange_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ipo_subscriptions", sa.Column("source_exchange", sa.String(20)))


def downgrade():
    op.drop_column("ipo_subscriptions", "source_exchange")

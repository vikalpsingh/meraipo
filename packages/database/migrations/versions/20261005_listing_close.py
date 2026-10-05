"""Persist the official listing-day close on each company."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_listing_close"
down_revision = "20261005_result_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("listing_price", sa.Numeric(20, 4)))
    op.add_column("companies", sa.Column("listing_price_date", sa.Date()))
    op.add_column("companies", sa.Column("listing_price_exchange", sa.String(3)))


def downgrade():
    op.drop_column("companies", "listing_price_exchange")
    op.drop_column("companies", "listing_price_date")
    op.drop_column("companies", "listing_price")

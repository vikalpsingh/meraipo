"""Persist one morning rendering per category and one daily delivery per subscriber."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_email_digests"
down_revision = "20261101_email_preferences"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_campaigns", sa.Column("digest_key", sa.String(40), nullable=True))
    op.add_column("email_campaigns", sa.Column("digest_payload", sa.JSON(), nullable=True))
    op.create_index("uq_email_campaigns_digest_key", "email_campaigns", ["digest_key"], unique=True)
    op.add_column("email_deliveries", sa.Column("digest_date", sa.Date(), nullable=True))
    op.create_index(
        "uq_email_delivery_day", "email_deliveries", ["subscriber_id", "digest_date"], unique=True
    )

    op.create_table(
        "email_digest_members",
        sa.Column(
            "campaign_id", sa.String(36), sa.ForeignKey("email_campaigns.id"), primary_key=True
        ),
        sa.Column("ipo_id", sa.String(36), sa.ForeignKey("ipos.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("email_digest_members")
    op.drop_index("uq_email_delivery_day", table_name="email_deliveries")
    op.drop_column("email_deliveries", "digest_date")
    op.drop_index("uq_email_campaigns_digest_key", table_name="email_campaigns")
    op.drop_column("email_campaigns", "digest_key")
    op.drop_column("email_campaigns", "digest_payload")

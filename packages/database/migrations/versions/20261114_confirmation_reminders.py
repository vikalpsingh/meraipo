"""Deduplicate weekly confirmation reminders."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_confirm_reminders"
down_revision = "20261113_ipo_intervals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_deliveries", sa.Column("reminder_week", sa.Date(), nullable=True))
    op.create_index(
        "uq_email_reminder_week",
        "email_deliveries",
        ["subscriber_id", "reminder_week"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_email_reminder_week", table_name="email_deliveries")
    op.drop_column("email_deliveries", "reminder_week")

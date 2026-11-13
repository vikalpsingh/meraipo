"""Configurable IPO intervals and weekend scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_ipo_intervals"
down_revision = "20261104_email_digests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduler_controls",
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scheduler_controls",
        sa.Column("saturday_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "scheduler_controls",
        sa.Column("sunday_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    for name in ("sunday_enabled", "saturday_enabled", "interval_hours"):
        op.drop_column("scheduler_controls", name)

"""Persist opening/closing application reminder preferences."""

import sqlalchemy as sa
from alembic import op

revision = "20261119_email_schedule"
down_revision = "20261118_x_schedules"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "email_control",
        sa.Column("application_schedule", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("email_control", "application_schedule")

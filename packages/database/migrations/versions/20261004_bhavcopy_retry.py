"""Persist Retry-After deadlines across worker runs."""

import sqlalchemy as sa
from alembic import op

revision = "20261004_bhavcopy_retry"
down_revision = "20261004_bhavcopy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bhavcopy_files", sa.Column("retry_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("bhavcopy_files", "retry_at")

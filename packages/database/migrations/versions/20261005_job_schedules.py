"""Independent exchange job schedules."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_job_schedules"
down_revision = "20261005_listing_close"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scheduler_controls", sa.Column("schedule_times", sa.JSON()))


def downgrade():
    op.drop_column("scheduler_controls", "schedule_times")

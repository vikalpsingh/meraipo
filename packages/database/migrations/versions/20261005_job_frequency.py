"""Hourly/daily/weekly schedules and the requested one-hour daily sequence."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_job_frequency"
down_revision = "20261005_job_schedules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduler_controls",
        sa.Column("frequency", sa.String(10), nullable=False, server_default="daily"),
    )
    op.add_column(
        "scheduler_controls", sa.Column("weekday", sa.Integer(), nullable=False, server_default="0")
    )
    connection = op.get_bind()
    controls = sa.table(
        "scheduler_controls",
        sa.column("name", sa.String()),
        sa.column("paused", sa.Boolean()),
        sa.column("schedule_times", sa.JSON()),
        sa.column("frequency", sa.String()),
        sa.column("weekday", sa.Integer()),
    )
    paused = dict(connection.execute(sa.select(controls.c.name, controls.c.paused)).all())
    for job, time in [
        ("sync-prices-nse", "19:00"),
        ("sync-prices-bse", "20:00"),
        ("sync-results-nse", "21:00"),
        ("sync-results-bse", "22:00"),
        ("sync-ipos", "23:00"),
    ]:
        values = dict(schedule_times=[time], frequency="daily", weekday=0)
        if job in paused:
            connection.execute(controls.update().where(controls.c.name == job).values(**values))
        else:
            parent = job.rsplit("-", 1)[0] if job != "sync-ipos" else job
            connection.execute(
                controls.insert().values(name=job, paused=paused.get(parent, False), **values)
            )
    sources = sa.table(
        "result_sources", sa.column("exchange", sa.String()), sa.column("schedule", sa.String())
    )
    for exchange, time in [("NSE", "21:00"), ("BSE", "22:00")]:
        connection.execute(
            sources.update().where(sources.c.exchange == exchange).values(schedule=time)
        )


def downgrade():
    op.drop_column("scheduler_controls", "weekday")
    op.drop_column("scheduler_controls", "frequency")

"""Operational controls and durable subscriber/IPO reservations; sending stays disabled."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_email_operations"
down_revision = "20261031_email_alerts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_campaigns", sa.Column("scheduled_at", sa.DateTime(timezone=True)))
    op.add_column(
        "email_deliveries",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("email_deliveries", sa.Column("retry_at", sa.DateTime(timezone=True)))
    op.add_column("email_deliveries", sa.Column("last_event", sa.String(30)))
    op.add_column("email_deliveries", sa.Column("last_event_at", sa.DateTime(timezone=True)))
    op.create_index("ix_email_deliveries_retry_at", "email_deliveries", ["retry_at"])
    op.create_table(
        "email_reservations",
        sa.Column(
            "subscriber_id", sa.String(36), sa.ForeignKey("email_subscribers.id"), primary_key=True
        ),
        sa.Column("ipo_id", sa.String(36), sa.ForeignKey("ipos.id"), primary_key=True),
        sa.Column("alert_type", sa.String(30), primary_key=True),
    )
    op.execute(
        "INSERT INTO email_reservations (subscriber_id, ipo_id, alert_type) SELECT DISTINCT d.subscriber_id,c.ipo_id,c.kind FROM email_deliveries d JOIN email_campaigns c ON c.id=d.campaign_id WHERE d.kind='ALERT'"
    )
    op.create_table(
        "email_control",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("sending_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scheduler_seen_at", sa.DateTime(timezone=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(36)),
        sa.Column("test_delivery_id", sa.String(36), sa.ForeignKey("email_deliveries.id")),
        sa.Column("test_received_at", sa.DateTime(timezone=True)),
        sa.Column("test_config_hash", sa.String(64)),
    )
    op.execute("INSERT INTO email_control(id,sending_enabled) VALUES ('email',false)")
    op.create_table(
        "email_dispatch_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80)),
    )


def downgrade():
    op.drop_column("email_campaigns", "scheduled_at")
    op.drop_table("email_dispatch_runs")
    op.drop_table("email_control")
    op.drop_table("email_reservations")
    op.drop_index("ix_email_deliveries_retry_at", table_name="email_deliveries")
    for name in ["last_event_at", "last_event", "retry_at", "attempt_count"]:
        op.drop_column("email_deliveries", name)

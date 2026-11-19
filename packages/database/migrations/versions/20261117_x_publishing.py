"""Approval-first X publishing ledger and encrypted connection."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_x_publishing"
down_revision = "20261114_confirm_reminders"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "x_accounts",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("user_id", sa.String(40)),
        sa.Column("username", sa.String(40)),
        sa.Column("tokens", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "x_posts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False, unique=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), unique=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("admin_users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("post_id", sa.String(40), unique=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("api_status", sa.Integer()),
        sa.Column("request_id", sa.String(100)),
    )
    op.execute("INSERT INTO x_accounts (id, auto_publish) VALUES ('meraipo', false)")


def downgrade():
    op.drop_table("x_posts")
    op.drop_table("x_accounts")

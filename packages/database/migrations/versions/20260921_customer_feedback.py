"""Customer feedback and idempotent browser votes."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_customer_feedback"
down_revision = "20260920_subscription_source"
branch_labels = None
depends_on = None


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "customer_feedback",
        *entity(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("author_hash", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.UniqueConstraint("author_hash", "request_key"),
    )
    op.create_index("ix_feedback_public", "customer_feedback", ["kind", "status", "created_at"])
    op.create_table(
        "customer_feedback_votes",
        *entity(),
        sa.Column(
            "feedback_id",
            sa.String(36),
            sa.ForeignKey("customer_feedback.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("voter_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("feedback_id", "voter_hash"),
    )
    op.create_index(
        "ix_customer_feedback_votes_feedback_id", "customer_feedback_votes", ["feedback_id"]
    )


def downgrade():
    op.drop_table("customer_feedback_votes")
    op.drop_table("customer_feedback")

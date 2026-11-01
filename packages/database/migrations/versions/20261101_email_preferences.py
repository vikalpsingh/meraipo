"""Optional encrypted contact profile and explicit GMP choice; legacy preferences unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_email_preferences"
down_revision = "20261101_email_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_subscribers", sa.Column("contact_encrypted", sa.Text(), nullable=True))
    op.add_column("email_subscribers", sa.Column("gmp_band", sa.String(20), nullable=True))
    op.create_index("ix_email_subscribers_gmp_band", "email_subscribers", ["gmp_band"])
    op.add_column(
        "email_deliveries", sa.Column("requested_profile_encrypted", sa.Text(), nullable=True)
    )


def downgrade():
    op.drop_column("email_deliveries", "requested_profile_encrypted")
    op.drop_index("ix_email_subscribers_gmp_band", table_name="email_subscribers")
    op.drop_column("email_subscribers", "gmp_band")
    op.drop_column("email_subscribers", "contact_encrypted")

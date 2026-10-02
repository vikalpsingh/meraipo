"""Cache advertisement logos locally."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_ad_logo_cache"
down_revision = "20260927_feature_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("advertisements", sa.Column("image_mime", sa.String(100), nullable=True))
    op.add_column("advertisements", sa.Column("image_data", sa.LargeBinary(), nullable=True))
    op.add_column("advertisements", sa.Column("image_sha256", sa.String(64), nullable=True))
    op.add_column(
        "advertisements", sa.Column("image_fetched_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("advertisements", "image_fetched_at")
    op.drop_column("advertisements", "image_sha256")
    op.drop_column("advertisements", "image_data")
    op.drop_column("advertisements", "image_mime")

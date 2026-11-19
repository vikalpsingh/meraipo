"""Independent X schedules and per-IPO publishing ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_x_schedules"
down_revision = "20261117_x_publishing"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "x_accounts", sa.Column("schedules", sa.JSON(), nullable=False, server_default="{}")
    )
    with op.batch_alter_table(
        "x_posts", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        # Discover PostgreSQL's generated name; SQLite unnamed constraints use the convention.
        constraints = sa.inspect(op.get_bind()).get_unique_constraints("x_posts")
        name = next((c["name"] for c in constraints if c["column_names"] == ["trading_date"]), None)
        batch.drop_constraint(name or "uq_x_posts_trading_date", type_="unique")
        batch.add_column(sa.Column("dedupe_key", sa.String(100)))
        batch.add_column(
            sa.Column("kind", sa.String(24), nullable=False, server_default="IPO_BRIEF")
        )
        batch.add_column(sa.Column("image_png", sa.LargeBinary()))
        batch.create_unique_constraint("uq_x_posts_dedupe_key", ["dedupe_key"])
    op.execute("UPDATE x_posts SET dedupe_key = 'legacy:' || id")


def downgrade():
    # Refuse destructive rollback when multiple posts exist for a date.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text("SELECT trading_date FROM x_posts GROUP BY trading_date HAVING count(*) > 1")
        )
        .first()
    )
    if duplicates:
        raise RuntimeError(
            "Archive the X ledger before schema rollback; multiple posts per date exist."
        )
    with op.batch_alter_table("x_posts") as batch:
        batch.drop_constraint("uq_x_posts_dedupe_key", type_="unique")
        batch.drop_column("image_png")
        batch.drop_column("kind")
        batch.drop_column("dedupe_key")
        batch.create_unique_constraint("uq_x_posts_trading_date", ["trading_date"])
    op.drop_column("x_accounts", "schedules")

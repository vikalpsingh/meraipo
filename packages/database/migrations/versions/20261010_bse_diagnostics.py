"""BSE stage diagnostics and approved official company result sources."""
import sqlalchemy as sa
from alembic import op

revision = "20261010_bse_diagnostics"
down_revision = "20261005_job_frequency"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("result_diagnostics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("data_import_runs.id"), nullable=False),
        sa.Column("exchange", sa.String(3), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_index("ix_result_diagnostics_run_id", "result_diagnostics", ["run_id"])
    op.create_table("company_result_sources",
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), primary_key=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("document_prefix", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("admin_users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table("company_result_sources")
    op.drop_index("ix_result_diagnostics_run_id", table_name="result_diagnostics")
    op.drop_table("result_diagnostics")

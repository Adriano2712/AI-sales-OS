"""campaigns, campaign_runs + RLS

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    campaign_status = postgresql.ENUM(
        "DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED", name="campaign_status"
    )

    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("segment", sa.String(100), nullable=False),
        sa.Column("cities", postgresql.ARRAY(sa.String), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("country", sa.String(2), nullable=False, server_default="BR"),
        sa.Column("target_quantity", sa.Integer, nullable=False),
        sa.Column("filters", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("status", campaign_status, nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_campaigns_tenant_id", "campaigns", ["tenant_id"])

    campaign_run_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", name="campaign_run_status"
    )

    op.create_table(
        "campaign_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", campaign_run_status, nullable=False, server_default="PENDING"),
        sa.Column("companies_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("companies_validated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enriched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("analyzed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opportunities", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_campaign_runs_tenant_id", "campaign_runs", ["tenant_id"])
    op.create_index("ix_campaign_runs_campaign_id", "campaign_runs", ["campaign_id"])

    # RLS — explicit, even though Supabase enables it by default on new tables
    # (see docs/SECURITY.md / migration 0002): relying on that default without
    # a policy fails closed but is useless, and future Supabase behavior isn't
    # a contract this codebase should depend on.
    for table in ("campaigns", "campaign_runs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
            """
        )


def downgrade() -> None:
    for table in ("campaign_runs", "campaigns"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("campaign_runs")
    op.execute("DROP TYPE IF EXISTS campaign_run_status;")
    op.drop_table("campaigns")
    op.execute("DROP TYPE IF EXISTS campaign_status;")

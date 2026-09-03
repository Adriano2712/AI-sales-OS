"""business_analyses + RLS

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("business_fit_score", sa.Float, nullable=True),
        sa.Column("activity_score", sa.Float, nullable=True),
        sa.Column("digital_maturity_score", sa.Float, nullable=True),
        sa.Column("need_score", sa.Float, nullable=True),
        sa.Column("compatibility_score", sa.Float, nullable=True),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("findings", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("problems", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_business_analyses_tenant_id", "business_analyses", ["tenant_id"])
    op.create_index("ix_business_analyses_company_id", "business_analyses", ["company_id"])

    op.execute("ALTER TABLE business_analyses ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON business_analyses
        USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON business_analyses;")
    op.execute("ALTER TABLE business_analyses DISABLE ROW LEVEL SECURITY;")
    op.drop_table("business_analyses")

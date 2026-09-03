"""opportunities + RLS

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    opportunity_type = postgresql.ENUM(
        "WEBSITE",
        "E_COMMERCE",
        "AUTOMATION",
        "INTERNAL_SYSTEM",
        "INTEGRATION",
        "DIGITAL_PRESENCE",
        "OTHER",
        name="opportunity_type",
    )
    opportunity_status = postgresql.ENUM(
        "OPEN", "REVIEWING", "APPROVED", "REJECTED", "ARCHIVED", name="opportunity_status"
    )
    opportunity_classification = postgresql.ENUM(
        "HIGH", "GOOD", "REVIEW", "LOW", name="opportunity_classification"
    )

    op.create_table(
        "opportunities",
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
        sa.Column("type", opportunity_type, nullable=False),
        sa.Column("status", opportunity_status, nullable=False, server_default="OPEN"),
        sa.Column("problem", sa.String(2000), nullable=True),
        sa.Column("potential_solution", sa.String(2000), nullable=True),
        sa.Column("reasons", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("digital_gap", sa.Float, nullable=True),
        sa.Column("business_fit", sa.Float, nullable=True),
        sa.Column("need", sa.Float, nullable=True),
        sa.Column("commercial_signals", sa.Float, nullable=True),
        sa.Column("opportunity_score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("classification", opportunity_classification, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "company_id", "type", name="uq_opportunity_company_type"),
    )
    op.create_index("ix_opportunities_tenant_id", "opportunities", ["tenant_id"])
    op.create_index("ix_opportunities_company_id", "opportunities", ["company_id"])

    op.execute("ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON opportunities
        USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON opportunities;")
    op.execute("ALTER TABLE opportunities DISABLE ROW LEVEL SECURITY;")
    op.drop_table("opportunities")
    op.execute("DROP TYPE IF EXISTS opportunity_type;")
    op.execute("DROP TYPE IF EXISTS opportunity_status;")
    op.execute("DROP TYPE IF EXISTS opportunity_classification;")

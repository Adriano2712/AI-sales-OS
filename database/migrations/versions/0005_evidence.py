"""evidence + RLS

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    evidence_confidence = postgresql.ENUM(
        "HIGH", "MEDIUM", "LOW", "UNKNOWN", name="evidence_confidence"
    )

    op.create_table(
        "evidence",
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
        sa.Column("claim", sa.String(500), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", evidence_confidence, nullable=False),
        sa.Column("supporting_data", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_tenant_id", "evidence", ["tenant_id"])
    op.create_index("ix_evidence_company_id", "evidence", ["company_id"])

    op.execute("ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON evidence
        USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON evidence;")
    op.execute("ALTER TABLE evidence DISABLE ROW LEVEL SECURITY;")
    op.drop_table("evidence")
    op.execute("DROP TYPE IF EXISTS evidence_confidence;")

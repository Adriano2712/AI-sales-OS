"""messages + RLS, companies.do_not_contact

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    message_channel = postgresql.ENUM(
        "EMAIL", "WHATSAPP", "LINKEDIN", "PHONE", "OTHER", name="message_channel"
    )
    message_status = postgresql.ENUM("DRAFT", "APPROVED", "REJECTED", "SENT", name="message_status")

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", message_channel, nullable=False),
        sa.Column("status", message_status, nullable=False, server_default="DRAFT"),
        sa.Column("generated_text", sa.String(4000), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(4000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_opportunity_id", "messages", ["opportunity_id"])

    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON messages
        USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
        """
    )

    op.add_column(
        "companies",
        sa.Column("do_not_contact", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("companies", "do_not_contact")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON messages;")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY;")
    op.drop_table("messages")
    op.execute("DROP TYPE IF EXISTS message_status;")
    op.execute("DROP TYPE IF EXISTS message_channel;")

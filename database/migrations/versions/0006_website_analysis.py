"""websites, website_pages, website_analyses + RLS

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    page_type = postgresql.ENUM(
        "HOMEPAGE", "CONTACT", "ABOUT", "SERVICES", "SCHEDULING", "OTHER",
        name="website_page_type",
    )

    op.create_table(
        "websites",
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
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "company_id", name="uq_website_company"),
    )
    op.create_index("ix_websites_tenant_id", "websites", ["tenant_id"])
    op.create_index("ix_websites_company_id", "websites", ["company_id"])

    op.create_table(
        "website_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "website_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("page_type", page_type, nullable=False),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("meta_description", sa.String(1000), nullable=True),
        sa.Column("has_viewport_meta", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_contact_form", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_phone_link", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_email_link", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_whatsapp_link", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_nav", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_custom_stylesheet", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("word_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_website_pages_tenant_id", "website_pages", ["tenant_id"])
    op.create_index("ix_website_pages_website_id", "website_pages", ["website_id"])

    op.create_table(
        "website_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "website_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("digital_score", sa.Float, nullable=True),
        sa.Column("score_funcionamento", sa.Float, nullable=True),
        sa.Column("score_mobile", sa.Float, nullable=True),
        sa.Column("score_ux", sa.Float, nullable=True),
        sa.Column("score_conversao", sa.Float, nullable=True),
        sa.Column("score_conteudo", sa.Float, nullable=True),
        sa.Column("score_design", sa.Float, nullable=True),
        sa.Column("findings", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_website_analyses_tenant_id", "website_analyses", ["tenant_id"])
    op.create_index("ix_website_analyses_website_id", "website_analyses", ["website_id"])

    for table in ("websites", "website_pages", "website_analyses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
            """
        )


def downgrade() -> None:
    for table in ("website_analyses", "website_pages", "websites"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("website_analyses")
    op.drop_table("website_pages")
    op.execute("DROP TYPE IF EXISTS website_page_type;")
    op.drop_table("websites")

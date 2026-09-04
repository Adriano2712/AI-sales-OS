"""companies.campaign_run_id

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "campaign_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_companies_campaign_run_id", "companies", ["campaign_run_id"])


def downgrade() -> None:
    op.drop_index("ix_companies_campaign_run_id", table_name="companies")
    op.drop_column("companies", "campaign_run_id")

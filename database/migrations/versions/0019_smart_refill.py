"""Smart Refill: CampaignRun refill/usable tracking (Fase 8)

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a real default (0) from the start — same reasoning as
    # every other CampaignRun counter (companies_found, duplicates, ...):
    # 0 is the honest value for every historical run, none of which ever
    # attempted a refill pass (the feature didn't exist).
    op.add_column(
        "campaign_runs", sa.Column("refill_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "campaign_runs",
        sa.Column("refill_companies_found", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaign_runs", sa.Column("usable_found", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "campaign_runs",
        sa.Column("skipped_already_contacted", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("campaign_runs", "skipped_already_contacted")
    op.drop_column("campaign_runs", "usable_found")
    op.drop_column("campaign_runs", "refill_companies_found")
    op.drop_column("campaign_runs", "refill_attempts")

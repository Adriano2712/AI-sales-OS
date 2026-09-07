"""Configurable autonomous discovery: Campaign.auto_discovery_enabled (Fase 9)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a real default (false) from the start — autonomy is
    # opt-in; every existing campaign genuinely never opted in (the field
    # didn't exist), so false is the honest value for every historical row,
    # not a guess.
    op.add_column(
        "campaigns",
        sa.Column("auto_discovery_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "auto_discovery_enabled")

"""Opportunity Score 2.0: campaign weights + score_components (Fase 7)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, no default value needed: None means "use
    # opportunities/scoring.py's system defaults" — a real, meaningful value
    # for every existing campaign, not an absence to backfill.
    op.add_column("campaigns", sa.Column("opportunity_weights", sa.JSON(), nullable=True))

    # NOT NULL with a real default from the start — like migration 0017's
    # Campaign.services, there's no ambiguity to classify: every existing
    # opportunity genuinely has no Score-2.0 breakdown yet (the field didn't
    # exist), so an empty object is the honest value for every historical row.
    op.add_column(
        "opportunities",
        sa.Column("score_components", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("opportunities", "score_components")
    op.drop_column("campaigns", "opportunity_weights")

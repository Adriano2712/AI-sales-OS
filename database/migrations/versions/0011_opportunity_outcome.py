"""opportunities.outcome + outcome_notes

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    opportunity_outcome = postgresql.ENUM(
        "CONTACTED", "REPLIED", "PROPOSAL_SENT", "WON", "LOST", name="opportunity_outcome"
    )
    opportunity_outcome.create(op.get_bind())

    op.add_column("opportunities", sa.Column("outcome", opportunity_outcome, nullable=True))
    op.add_column("opportunities", sa.Column("outcome_notes", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "outcome_notes")
    op.drop_column("opportunities", "outcome")
    op.execute("DROP TYPE IF EXISTS opportunity_outcome;")

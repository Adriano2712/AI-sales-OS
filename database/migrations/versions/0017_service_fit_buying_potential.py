"""Campaign.services (ICP) + SERVICE_FIT_SCORE + BUYING_POTENTIAL (Fase 6)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a real default from the start — unlike Evidence's
    # polarity/category (Fase 3), there's no ambiguity to classify here:
    # every existing campaign genuinely has no stated services yet (the
    # field didn't exist), so an empty array is the honest, not a guessed,
    # value for every historical row.
    op.add_column(
        "campaigns",
        sa.Column(
            "services", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
    )

    # Nullable, no backfill possible or attempted — historical
    # business_analyses rows predate these fields and have no real AI
    # output to recover them from; NULL here correctly means "not computed
    # under the old schema", a genuine absence, not an invented value.
    op.add_column("business_analyses", sa.Column("service_fit_score", sa.Float(), nullable=True))
    op.add_column(
        "business_analyses", sa.Column("buying_potential_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "business_analyses",
        sa.Column("buying_potential_summary", sa.String(300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("business_analyses", "buying_potential_summary")
    op.drop_column("business_analyses", "buying_potential_score")
    op.drop_column("business_analyses", "service_fit_score")
    op.drop_column("campaigns", "services")

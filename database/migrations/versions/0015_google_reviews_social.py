"""Google Review + Social Intelligence (Fase 4)

Adds four company columns (all nullable, no backfill needed — these are
optional attributes that were simply never collected before, not required
data with a knowable value for existing rows) and one new evidence_category
enum value.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("google_place_id", sa.String(200), nullable=True))
    op.add_column("companies", sa.Column("google_rating", sa.Float(), nullable=True))
    op.add_column("companies", sa.Column("google_review_count", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("instagram_url", sa.String(500), nullable=True))

    # Non-breaking enum extension (see evidence/enums.py's EvidenceCategory
    # docstring, which anticipated exactly this in Fase 3). Not used within
    # this same migration/transaction — Postgres forbids that for a value
    # just added via ALTER TYPE ... ADD VALUE.
    op.execute("ALTER TYPE evidence_category ADD VALUE IF NOT EXISTS 'CUSTOMER_VALIDATION'")


def downgrade() -> None:
    op.drop_column("companies", "instagram_url")
    op.drop_column("companies", "google_review_count")
    op.drop_column("companies", "google_rating")
    op.drop_column("companies", "google_place_id")
    # Postgres has no DROP VALUE for enums — removing 'CUSTOMER_VALIDATION'
    # would require rebuilding the type (drop+recreate+recast the column),
    # which risks data loss if any row already uses it. Left in place, same
    # accepted asymmetry as any other additive enum migration in this
    # project — downgrade doesn't fully undo Fase 4 evidence data either.

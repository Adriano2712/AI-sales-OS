"""evidence.polarity + evidence.category (Opportunity Signal, Fase 3)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    evidence_polarity = postgresql.ENUM(
        "POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN", name="evidence_polarity"
    )
    evidence_polarity.create(op.get_bind())
    evidence_category = postgresql.ENUM(
        "CONTACTABILITY",
        "SOCIAL_PRESENCE",
        "BUSINESS_STATUS",
        "BUSINESS_ANALYSIS",
        "OTHER",
        name="evidence_category",
    )
    evidence_category.create(op.get_bind())

    # Nullable first — real rows already exist (this ran against a live
    # tenant's data, not a fresh table), backfilled below before the NOT
    # NULL is applied. Classification mirrors evidence/service.py's real
    # call sites (enrichment/service.py, business_analysis/service.py) at
    # the time each row was created.
    op.add_column("evidence", sa.Column("polarity", evidence_polarity, nullable=True))
    op.add_column("evidence", sa.Column("category", evidence_category, nullable=True))

    # Absolute rule first: UNKNOWN confidence is always UNKNOWN polarity,
    # regardless of which field it's about.
    op.execute("UPDATE evidence SET polarity = 'UNKNOWN' WHERE confidence = 'UNKNOWN'")
    op.execute(
        "UPDATE evidence SET category = 'CONTACTABILITY' "
        "WHERE confidence = 'UNKNOWN' AND supporting_data->>'field' IN ('phone', 'website', 'email')"
    )

    # business_analysis/service.py: findings are neutral observations,
    # problems are positive opportunity signals by construction (the AI
    # Analyst's own prompt scopes "problems" to service-relevant gaps).
    op.execute(
        "UPDATE evidence SET polarity = 'NEUTRAL', category = 'BUSINESS_ANALYSIS' "
        "WHERE supporting_data->>'kind' = 'finding'"
    )
    op.execute(
        "UPDATE evidence SET polarity = 'POSITIVE', category = 'BUSINESS_ANALYSIS' "
        "WHERE supporting_data->>'kind' = 'problem'"
    )

    # enrichment/service.py: real contact info found (HIGH confidence).
    op.execute(
        "UPDATE evidence SET polarity = 'POSITIVE', category = 'CONTACTABILITY' "
        "WHERE confidence = 'HIGH' AND supporting_data->>'field' IN ('phone', 'website', 'email')"
    )
    op.execute(
        "UPDATE evidence SET polarity = 'NEGATIVE', category = 'BUSINESS_STATUS' "
        "WHERE supporting_data->>'field' = 'permanently_closed'"
    )
    op.execute(
        "UPDATE evidence SET polarity = 'POSITIVE', category = 'SOCIAL_PRESENCE' "
        "WHERE supporting_data->>'field' IN ('facebook', 'instagram')"
    )
    op.execute(
        "UPDATE evidence SET polarity = 'NEUTRAL', category = 'BUSINESS_STATUS' "
        "WHERE supporting_data->>'field' = 'opening_hours'"
    )
    op.execute(
        "UPDATE evidence SET polarity = 'NEUTRAL', category = 'OTHER' "
        "WHERE supporting_data->>'field' IN ('cuisine', 'category')"
    )

    # Catch-all for anything unclassified above (defensive — real data as of
    # this migration has none left unmatched, verified before writing this).
    op.execute("UPDATE evidence SET polarity = 'NEUTRAL' WHERE polarity IS NULL")
    op.execute("UPDATE evidence SET category = 'OTHER' WHERE category IS NULL")

    op.alter_column("evidence", "polarity", nullable=False)
    op.alter_column("evidence", "category", nullable=False)


def downgrade() -> None:
    op.drop_column("evidence", "category")
    op.drop_column("evidence", "polarity")
    op.execute("DROP TYPE IF EXISTS evidence_category;")
    op.execute("DROP TYPE IF EXISTS evidence_polarity;")

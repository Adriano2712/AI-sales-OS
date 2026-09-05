"""Website status + WEBSITE_OPPORTUNITY_SCORE (Fase 5)

Adds website_analyses.status (WebsiteStatus) and .opportunity_score, plus
the new evidence_category value WEBSITE_QUALITY.

Backfill is real-data-driven — verified against this project's own 39
existing website_analyses rows before writing this (see
docs/WEBSITE_ANALYSIS.md's Fase 5 section):

- 11 rows had digital_score = 0.0 — every one of them was actually a fetch
  failure (5 real HTTP 403 responses, 1 HTTP 404, 1 no-status/connection
  failure, 4 older rows with no `problems` key but a visible HTTP 404 or a
  null status in their raw `pages` findings), not a real "worst possible
  quality" reading. This confirms the bug fixed in scoring.py's
  compute_sub_scores: an unreachable homepage was scoring funcionamento=0.0
  (and, since nothing else was evaluable, digital_score=0.0) instead of
  staying None. The 5 HTTP-403 rows are reclassified BLOCKED (a real
  anti-bot signal); the other 6 are OFFLINE (a real failure, no anti-bot
  signal detected). Their digital_score/score_funcionamento are nulled out
  to match what the fixed code now produces for the same situation.
- The remaining 28 rows had real, evaluated content (>=4 of 6 sub-score
  dimensions non-null in every one of them — no historical row needs the
  new ANALYZED status) and are bucketed by the same GOOD/NEEDS_IMPROVEMENT/
  POOR thresholds status.py now uses going forward.

opportunity_score is backfilled from the already-stored score_conversao
(100 - score_conversao) wherever that column is non-null — real data, not
a guess; stays null where score_conversao is null (including the newly
nulled-out BLOCKED/OFFLINE rows).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    website_status = postgresql.ENUM(
        "WEBSITE_NOT_FOUND",
        "OFFLINE",
        "BLOCKED",
        "JS_REQUIRED",
        "TIMEOUT",
        "UNKNOWN",
        "ANALYZED",
        "GOOD",
        "NEEDS_IMPROVEMENT",
        "POOR",
        name="website_status",
    )
    website_status.create(op.get_bind())

    op.add_column("website_analyses", sa.Column("status", website_status, nullable=True))
    op.add_column("website_analyses", sa.Column("opportunity_score", sa.Float(), nullable=True))

    # BLOCKED: a real anti-bot/WAF signal (HTTP 403) — never a quality
    # judgment (the Fase 5 absolute rule).
    op.execute(
        "UPDATE website_analyses SET status = 'BLOCKED' "
        "WHERE digital_score = 0.0 AND (findings->'pages'->0->>'status')::int = 403"
    )
    # Everything else that scored 0.0 was some other real fetch failure
    # (404, no status/connection failure) with no anti-bot signal detected.
    op.execute(
        "UPDATE website_analyses SET status = 'OFFLINE' "
        "WHERE digital_score = 0.0 AND status IS NULL"
    )
    # Fix the misleading pre-fix score data on both reclassified groups —
    # matches what the fixed compute_sub_scores now produces for the same
    # situation (None, not 0.0).
    op.execute(
        "UPDATE website_analyses SET digital_score = NULL, score_funcionamento = NULL "
        "WHERE status IN ('BLOCKED', 'OFFLINE')"
    )

    # Remaining rows have real, evaluated content — bucket by the same
    # thresholds status.py uses going forward.
    op.execute(
        "UPDATE website_analyses SET status = (CASE "
        "WHEN digital_score >= 70 THEN 'GOOD' "
        "WHEN digital_score >= 40 THEN 'NEEDS_IMPROVEMENT' "
        "ELSE 'POOR' END)::website_status "
        "WHERE status IS NULL"
    )
    # Defensive catch-all — verified nothing real hits this, kept for the
    # same reason migration 0014's did.
    op.execute("UPDATE website_analyses SET status = 'UNKNOWN' WHERE status IS NULL")

    op.execute(
        "UPDATE website_analyses SET opportunity_score = ROUND((100.0 - score_conversao)::numeric, 1) "
        "WHERE score_conversao IS NOT NULL"
    )

    op.alter_column("website_analyses", "status", nullable=False)

    # Non-breaking enum extension (same pattern as migration 0015's
    # CUSTOMER_VALIDATION addition).
    op.execute("ALTER TYPE evidence_category ADD VALUE IF NOT EXISTS 'WEBSITE_QUALITY'")


def downgrade() -> None:
    op.drop_column("website_analyses", "opportunity_score")
    op.drop_column("website_analyses", "status")
    op.execute("DROP TYPE IF EXISTS website_status;")
    # Postgres has no DROP VALUE for enums — same accepted asymmetry as
    # migration 0015's downgrade.

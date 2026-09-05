import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin


class BusinessAnalysis(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """Append-only, one row per analysis run — same reasoning as
    WebsiteAnalysis (spec section 58's data model, score history over time).
    Deterministic sub-scores (activity/digital_maturity/need) and AI-derived
    ones (business_fit/compatibility) live side by side; see
    docs/BUSINESS_ANALYSIS.md for which is which and why."""

    __tablename__ = "business_analyses"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    business_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    digital_maturity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    need_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    compatibility_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fase 6. Distinct from business_fit_score: fit against the specific
    # service(s) the owning campaign is actually selling, not a generic
    # prospect judgment. Nullable — historical rows predate this field and
    # have no real value to backfill it with (see migration 0017).
    service_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fase 6. Strength of observed buying-related signals — never a
    # probability or claim of purchase intent (enforced at the AI output
    # schema level, see ai_analyst.py's banned-phrase validator).
    buying_potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    buying_potential_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Score != confidence (spec section 42) — how sure the AI is in its own
    # business_fit/compatibility judgment, not how good the business is.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    problems: Mapped[list] = mapped_column(JSON, default=list)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

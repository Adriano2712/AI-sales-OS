import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey
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
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Score != confidence (spec section 42) — how sure the AI is in its own
    # business_fit/compatibility judgment, not how good the business is.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    problems: Mapped[list] = mapped_column(JSON, default=list)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

import uuid

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
    OpportunityStatus,
    OpportunityType,
)


class Opportunity(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """One row per (company, type) — updated in place on re-scoring, unlike
    the append-only WebsiteAnalysis/BusinessAnalysis. An opportunity is a
    record a human works (status, future activity history), so recomputing
    its score shouldn't spawn a new row every pipeline re-run; idempotency
    (spec section 54) comes from the unique constraint below."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "company_id", "type", name="uq_opportunity_company_type"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[OpportunityType] = mapped_column(Enum(OpportunityType, name="opportunity_type"))
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus, name="opportunity_status"), default=OpportunityStatus.OPEN
    )
    problem: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    potential_solution: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    digital_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    business_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    need: Mapped[float | None] = mapped_column(Float, nullable=True)
    commercial_signals: Mapped[float | None] = mapped_column(Float, nullable=True)
    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Score != confidence (spec section 42). Fase 7 (Opportunity Score 2.0):
    # OPPORTUNITY_CONFIDENCE, blending BusinessAnalysis.confidence with how
    # complete the factor set behind opportunity_score actually was — see
    # opportunities/scoring.py::compute_opportunity_confidence. No longer a
    # naive pass-through of BusinessAnalysis.confidence (its pre-Fase-7
    # behavior).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fase 7: full breakdown behind opportunity_score/confidence (per-factor
    # values, weights actually used, penalty points/reasons) — transparency/
    # debugging, never itself read back into scoring.
    score_components: Mapped[dict] = mapped_column(JSON, default=dict)
    classification: Mapped[OpportunityClassification | None] = mapped_column(
        Enum(OpportunityClassification, name="opportunity_classification"), nullable=True
    )
    # Nullable = "not tracked yet", never a fabricated default (spec section
    # 35) — most opportunities never get contacted at all.
    outcome: Mapped[OpportunityOutcome | None] = mapped_column(
        Enum(OpportunityOutcome, name="opportunity_outcome"), nullable=True
    )
    outcome_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

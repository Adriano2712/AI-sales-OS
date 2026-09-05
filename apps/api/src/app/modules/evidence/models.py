import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity


class Evidence(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """The Opportunity Signal (Fase 3): every observable fact that feeds a
    commercial judgment about a company lives here, one row per claim, with
    its source, confidence, and — since Fase 3 — polarity/category. Not a
    separate `Signal` table: this already was "an observable claim with a
    confidence level," Fase 3 only added what was missing (does this claim
    help or hurt the opportunity, and what kind of signal is it)."""

    __tablename__ = "evidence"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    claim: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[EvidenceConfidence] = mapped_column(
        Enum(EvidenceConfidence, name="evidence_confidence")
    )
    # No column default on purpose (mirrors confidence) — every call site
    # must decide explicitly. evidence/service.py enforces the one rule that
    # can't be left to convention: confidence=UNKNOWN implies polarity=UNKNOWN.
    polarity: Mapped[EvidencePolarity] = mapped_column(
        Enum(EvidencePolarity, name="evidence_polarity")
    )
    category: Mapped[EvidenceCategory] = mapped_column(
        Enum(EvidenceCategory, name="evidence_category")
    )
    supporting_data: Mapped[dict] = mapped_column(JSON, default=dict)

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.evidence.enums import EvidenceConfidence


class Evidence(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
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
    supporting_data: Mapped[dict] = mapped_column(JSON, default=dict)

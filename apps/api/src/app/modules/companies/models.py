import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.companies.enums import CompanyStatus


class Company(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    # Free text, not a Python enum — same reasoning as Campaign.segment.
    segment: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str] = mapped_column(String(200), index=True)
    state: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="BR")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus, name="company_status"), default=CompanyStatus.DISCOVERED
    )
    # True when identity resolution found a MEDIUM-confidence possible duplicate
    # (spec section 27 — never auto-merged, but worth surfacing). No review UI
    # yet; that's Fase 7 (Dashboard). See app.modules.companies.service.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Spec section 50 — implemented as a flag on Company rather than a
    # separate `do_not_contact` table: Discovery never collected a named
    # personal contact (only public business phone/website, spec section 65),
    # so there's no distinct "contact" entity to attach this to yet. Checked
    # by messages/service.py before generating or sending any message.
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which run first discovered this company — nullable (a company created
    # outside a campaign run has none). Only ever set at creation, never on a
    # later merge (see companies/service.py:upsert_company_from_raw), so it
    # means "first discovered by", not "most recently touched by" — that's
    # what lets the daily digest (workers/scheduler.py) report exactly the
    # companies a given run actually introduced, without re-reporting one a
    # later run merely re-matched as a duplicate.
    campaign_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )


class CompanySource(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "company_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_company_source"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON, default=dict)

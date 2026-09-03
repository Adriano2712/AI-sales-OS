import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus


class Campaign(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200))
    # Free text, not a Python enum: segments/cities must stay configurable
    # without a code deploy (spec section 9) — validated at the API layer,
    # not the schema layer.
    segment: Mapped[str] = mapped_column(String(100))
    cities: Mapped[list[str]] = mapped_column(ARRAY(String))
    state: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="BR")
    target_quantity: Mapped[int] = mapped_column(Integer)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"), default=CampaignStatus.DRAFT
    )


class CampaignRun(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "campaign_runs"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CampaignRunStatus] = mapped_column(
        Enum(CampaignRunStatus, name="campaign_run_status"), default=CampaignRunStatus.PENDING
    )
    companies_found: Mapped[int] = mapped_column(Integer, default=0)
    companies_validated: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    enriched: Mapped[int] = mapped_column(Integer, default=0)
    analyzed: Mapped[int] = mapped_column(Integer, default=0)
    opportunities: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)

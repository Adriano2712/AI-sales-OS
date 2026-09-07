import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String
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
    # Fase 6 (ICP: "services" dimension) — the service(s) this campaign is
    # actually selling, e.g. ["website", "e-commerce"]. Free strings, same
    # reasoning as `segment` (no code deploy needed to add a new service
    # offering). Empty by default: this is the one new ICP field with a real
    # immediate consumer (SERVICE_FIT_SCORE, business_analysis/ai_analyst.py)
    # — the AI falls back to a generic software-house service list when this
    # is empty, exactly like it already did before this field existed.
    services: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # Fase 7 (Opportunity Score 2.0) — a campaign-level override of
    # opportunities/scoring.py's DEFAULT_WEIGHTS_V2. Nullable/None means
    # "use the system defaults", not "zero out every factor" — see
    # opportunities/schemas.py::OpportunityWeights.to_weights_dict(), which
    # merges whatever's set here over the defaults rather than replacing
    # them wholesale.
    opportunity_weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Fase 9 (configurable autonomous discovery) — opts THIS campaign into
    # the scheduler's daily sweep (workers/scheduler.py::
    # _trigger_autonomous_campaign_runs_all_tenants), reusing its own real
    # segment/cities/state/country/target_quantity/services/
    # opportunity_weights rather than the single hardcoded pilot tenant/
    # segment-rotation/nationwide-only campaign the scheduler's pre-
    # existing `_tick` still drives unchanged. False by default — autonomy
    # is opt-in per campaign, never silently on. See campaigns/service.py's
    # _MAX_AUTONOMOUS_TARGET_QUANTITY for the cost-safety cap enforced
    # alongside this flag.
    auto_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
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
    # Fase 8 (Smart Refill). Deliberately separate from companies_found/
    # validated/duplicates/enriched/analyzed above, which stay exactly what
    # the original single pass produced (API/dashboard backward-
    # compatibility) — refill is extra work on top, tracked in its own
    # fields. refill_attempts=0 means the run hit target_quantity (or had
    # no workable supply left) without ever needing a second pass.
    refill_attempts: Mapped[int] = mapped_column(Integer, default=0)
    refill_companies_found: Mapped[int] = mapped_column(Integer, default=0)
    # The real, authoritative "did this run hit its target" number — workable
    # companies (not INVALID, not do_not_contact, not already-contacted
    # anywhere in the tenant) across the original pass plus any refill
    # passes. See jobs/handlers/discovery.py::_count_usable_companies.
    usable_found: Mapped[int] = mapped_column(Integer, default=0)
    skipped_already_contacted: Mapped[int] = mapped_column(Integer, default=0)

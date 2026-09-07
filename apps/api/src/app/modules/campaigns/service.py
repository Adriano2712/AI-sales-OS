import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campaigns.enums import VALID_STATUS_TRANSITIONS, CampaignRunStatus, CampaignStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.campaigns.schemas import CampaignCreate, CampaignUpdate


class InvalidStatusTransition(ValueError):
    def __init__(self, current: CampaignStatus, new: CampaignStatus) -> None:
        super().__init__(f"Cannot transition campaign from {current} to {new}")
        self.current = current
        self.new = new


class CampaignNotActive(ValueError):
    """Raised when a run is requested for a campaign that isn't ACTIVE."""


# Fase 9 (configurable autonomous discovery) — the master spec's own
# escalation discipline, enforced in code rather than left to hope: start
# small (3, then 10), never a large batch unattended. Autonomous means the
# scheduler creates a fresh run every day with nobody re-approving each
# one, so an uncapped target_quantity here would be real, compounding,
# unattended cost (~$0.01-0.013 per company just for business_analysis,
# see docs/DAILY_DIGEST.md) — this cap is intentionally the same ceiling
# already validated in real production use (docs/DISCOVERY.md's Fase 9
# pilot). A human running a one-off manual campaign (auto_discovery_
# enabled=False) is unaffected — they're already re-approving each run by
# clicking "start run."
_MAX_AUTONOMOUS_TARGET_QUANTITY = 10


class AutonomousDiscoveryLimitExceeded(ValueError):
    def __init__(self, target_quantity: int) -> None:
        super().__init__(
            f"target_quantity={target_quantity} exceeds the autonomous-discovery "
            f"limit of {_MAX_AUTONOMOUS_TARGET_QUANTITY} — a campaign that runs "
            "unattended every day must start small (spec: 3, then 10, never a "
            "large batch at once). Lower target_quantity, or set "
            "auto_discovery_enabled=False and start runs manually instead."
        )
        self.target_quantity = target_quantity


def validate_status_transition(current: CampaignStatus, new: CampaignStatus) -> None:
    """Pure function, no DB — unit-testable in isolation (see spec section 68:
    state transitions belong in unit tests, not integration tests)."""
    if new == current:
        return
    if new not in VALID_STATUS_TRANSITIONS[current]:
        raise InvalidStatusTransition(current, new)


async def create_campaign(
    db: AsyncSession, tenant_id: uuid.UUID, data: CampaignCreate
) -> Campaign:
    if data.auto_discovery_enabled and data.target_quantity > _MAX_AUTONOMOUS_TARGET_QUANTITY:
        raise AutonomousDiscoveryLimitExceeded(data.target_quantity)
    campaign = Campaign(tenant_id=tenant_id, **data.model_dump())
    db.add(campaign)
    await db.flush()
    return campaign


async def list_campaigns(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: CampaignStatus | None = None,
    segment: str | None = None,
    city: str | None = None,
) -> list[Campaign]:
    query = select(Campaign).where(Campaign.tenant_id == tenant_id)
    if status is not None:
        query = query.where(Campaign.status == status)
    if segment is not None:
        query = query.where(Campaign.segment == segment)
    if city is not None:
        query = query.where(Campaign.cities.contains([city]))
    query = query.order_by(Campaign.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars())


async def get_campaign(
    db: AsyncSession, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign | None:
    result = await db.execute(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.id == campaign_id)
    )
    return result.scalar_one_or_none()


async def update_campaign(
    db: AsyncSession, campaign: Campaign, data: CampaignUpdate
) -> Campaign:
    updates = data.model_dump(exclude_unset=True, exclude={"status"})

    # Checked against the *resolved* final state (existing value merged with
    # whatever this partial update actually touches) — a PATCH that only
    # sets auto_discovery_enabled=True without re-sending target_quantity
    # must still be caught if the campaign's existing target_quantity is
    # already over the autonomous-discovery cap, and vice versa.
    resolved_auto_discovery = updates.get("auto_discovery_enabled", campaign.auto_discovery_enabled)
    resolved_target_quantity = updates.get("target_quantity", campaign.target_quantity)
    if resolved_auto_discovery and resolved_target_quantity > _MAX_AUTONOMOUS_TARGET_QUANTITY:
        raise AutonomousDiscoveryLimitExceeded(resolved_target_quantity)

    for field, value in updates.items():
        setattr(campaign, field, value)

    if data.status is not None:
        validate_status_transition(campaign.status, data.status)
        campaign.status = data.status

    await db.flush()
    return campaign


async def list_runs(
    db: AsyncSession, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[CampaignRun]:
    result = await db.execute(
        select(CampaignRun)
        .where(CampaignRun.tenant_id == tenant_id, CampaignRun.campaign_id == campaign_id)
        .order_by(CampaignRun.created_at.desc())
    )
    return list(result.scalars())


async def get_run(
    db: AsyncSession, tenant_id: uuid.UUID, campaign_id: uuid.UUID, run_id: uuid.UUID
) -> CampaignRun | None:
    result = await db.execute(
        select(CampaignRun).where(
            CampaignRun.tenant_id == tenant_id,
            CampaignRun.campaign_id == campaign_id,
            CampaignRun.id == run_id,
        )
    )
    return result.scalar_one_or_none()


async def create_run(db: AsyncSession, campaign: Campaign) -> CampaignRun:
    """Creates the run record. Does not enqueue any discovery job yet — there is
    no discovery job type until Fase 2. This only proves the campaign -> run
    relationship and gives Fase 2 something to attach a worker to."""
    if campaign.status != CampaignStatus.ACTIVE:
        raise CampaignNotActive(f"Campaign is {campaign.status}, must be ACTIVE to start a run")

    run = CampaignRun(
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.id,
        started_at=datetime.now(UTC),
        status=CampaignRunStatus.PENDING,
    )
    db.add(run)
    await db.flush()
    return run

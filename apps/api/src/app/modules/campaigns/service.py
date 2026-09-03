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

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.campaigns.enums import CampaignStatus
from app.modules.campaigns.schemas import (
    CampaignCreate,
    CampaignRead,
    CampaignRunRead,
    CampaignUpdate,
)
from app.modules.campaigns.service import (
    CampaignNotActive,
    InvalidStatusTransition,
    create_campaign,
    create_run,
    get_campaign,
    get_run,
    list_campaigns,
    list_runs,
    update_campaign,
)
from app.modules.jobs.enums import JobType
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db, require_write_access
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _get_campaign_or_404(db: AsyncSession, tenant_id: uuid.UUID, campaign_id: uuid.UUID):
    campaign = await get_campaign(db, tenant_id, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
async def create_campaign_endpoint(
    data: CampaignCreate,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> CampaignRead:
    campaign = await create_campaign(db, context.tenant_id, data)
    await log_event(
        db, context.tenant_id, AuditEventType.CAMPAIGN_CREATED, {"campaign_id": str(campaign.id)}
    )
    await db.commit()
    return CampaignRead.model_validate(campaign)


@router.get("", response_model=list[CampaignRead])
async def list_campaigns_endpoint(
    status_filter: CampaignStatus | None = Query(default=None, alias="status"),
    segment: str | None = None,
    city: str | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[CampaignRead]:
    campaigns = await list_campaigns(db, context.tenant_id, status_filter, segment, city)
    return [CampaignRead.model_validate(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign_endpoint(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> CampaignRead:
    campaign = await _get_campaign_or_404(db, context.tenant_id, campaign_id)
    return CampaignRead.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignRead)
async def update_campaign_endpoint(
    campaign_id: uuid.UUID,
    data: CampaignUpdate,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> CampaignRead:
    campaign = await _get_campaign_or_404(db, context.tenant_id, campaign_id)
    try:
        campaign = await update_campaign(db, campaign, data)
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await log_event(
        db, context.tenant_id, AuditEventType.CAMPAIGN_UPDATED, {"campaign_id": str(campaign.id)}
    )
    await db.commit()
    return CampaignRead.model_validate(campaign)


@router.post(
    "/{campaign_id}/runs", response_model=CampaignRunRead, status_code=status.HTTP_201_CREATED
)
async def create_run_endpoint(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> CampaignRunRead:
    campaign = await _get_campaign_or_404(db, context.tenant_id, campaign_id)
    try:
        run = await create_run(db, campaign)
    except CampaignNotActive as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    job = await get_or_create_job(
        db,
        tenant_id=context.tenant_id,
        job_type=JobType.DISCOVERY,
        idempotency_key=str(run.id),
        payload={"campaign_run_id": str(run.id)},
    )
    await log_event(
        db,
        context.tenant_id,
        AuditEventType.CAMPAIGN_STARTED,
        {"campaign_id": str(campaign.id), "run_id": str(run.id), "job_id": str(job.id)},
    )
    await db.commit()

    get_queue().enqueue(
        "app.modules.jobs.handlers.discovery.run",
        str(job.id),
        str(context.tenant_id),
        str(run.id),
    )

    return CampaignRunRead.model_validate(run)


@router.get("/{campaign_id}/runs", response_model=list[CampaignRunRead])
async def list_runs_endpoint(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[CampaignRunRead]:
    await _get_campaign_or_404(db, context.tenant_id, campaign_id)
    runs = await list_runs(db, context.tenant_id, campaign_id)
    return [CampaignRunRead.model_validate(r) for r in runs]


@router.get("/{campaign_id}/runs/{run_id}", response_model=CampaignRunRead)
async def get_run_endpoint(
    campaign_id: uuid.UUID,
    run_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> CampaignRunRead:
    await _get_campaign_or_404(db, context.tenant_id, campaign_id)
    run = await get_run(db, context.tenant_id, campaign_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return CampaignRunRead.model_validate(run)

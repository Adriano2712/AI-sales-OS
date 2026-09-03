import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.companies.models import Company
from app.modules.companies.service import get_company
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity
from app.modules.opportunities.schemas import OpportunityDetailRead, OpportunityRead, OpportunityUpdate
from app.modules.opportunities.scoring import derive_next_action
from app.modules.opportunities.service import (
    get_opportunity,
    list_opportunities,
    update_opportunity_status,
)
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db, require_write_access
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _to_detail(opportunity: Opportunity, company: Company) -> OpportunityDetailRead:
    return OpportunityDetailRead(
        **OpportunityRead.model_validate(opportunity).model_dump(),
        company_name=company.name,
        company_segment=company.segment,
        company_city=company.city,
        company_state=company.state,
        company_phone=company.phone,
        company_website=company.website,
        next_action=derive_next_action(opportunity.status),
        company_do_not_contact=company.do_not_contact,
    )


@router.get("", response_model=list[OpportunityDetailRead])
async def list_opportunities_endpoint(
    segment: str | None = None,
    city: str | None = None,
    status_filter: OpportunityStatus | None = Query(default=None, alias="status"),
    type_filter: OpportunityType | None = Query(default=None, alias="type"),
    min_score: float | None = None,
    min_confidence: float | None = None,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[OpportunityDetailRead]:
    """Spec section 46 filters: score, confidence, segment, city, status,
    opportunity type. Response includes company name/segment/city and
    next_action (spec section 46's dashboard fields) — a per-row company
    lookup, not a concern at this project's scale (dozens of opportunities,
    spec section 9)."""
    opportunities = await list_opportunities(
        db, context.tenant_id, segment, city, status_filter, type_filter, min_score, min_confidence
    )
    results = []
    for opportunity in opportunities:
        company = await get_company(db, context.tenant_id, opportunity.company_id)
        if company is None:
            continue
        results.append(_to_detail(opportunity, company))
    return results


@router.get("/{opportunity_id}", response_model=OpportunityDetailRead)
async def get_opportunity_endpoint(
    opportunity_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> OpportunityDetailRead:
    opportunity = await get_opportunity(db, context.tenant_id, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    company = await get_company(db, context.tenant_id, opportunity.company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return _to_detail(opportunity, company)


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
async def update_opportunity_endpoint(
    opportunity_id: uuid.UUID,
    data: OpportunityUpdate,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> OpportunityRead:
    """Status-only, same shape as PATCH /companies/{id} — a human moving an
    opportunity through OPEN -> REVIEWING -> APPROVED/REJECTED/ARCHIVED
    (spec section 47's human-approval gate, minus the message-generation
    step which is Fase 8)."""
    opportunity = await get_opportunity(db, context.tenant_id, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    opportunity = await update_opportunity_status(db, opportunity, data.status)
    await log_event(
        db,
        context.tenant_id,
        AuditEventType.OPPORTUNITY_UPDATED,
        {"opportunity_id": str(opportunity.id), "status": data.status.value},
    )
    await db.commit()
    return OpportunityRead.model_validate(opportunity)

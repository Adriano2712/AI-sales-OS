import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.business_analysis.schemas import BusinessAnalysisRead
from app.modules.business_analysis.service import get_latest_business_analysis
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.schemas import (
    CompanyDetailRead,
    CompanyRead,
    CompanySourceRead,
    CompanyUpdate,
)
from app.modules.companies.service import (
    get_company,
    list_companies,
    list_sources,
    update_company,
)
from app.modules.evidence.schemas import EvidenceRead
from app.modules.evidence.service import list_evidence_for_company
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db, require_write_access
from app.modules.tenancy.schemas import TenantContext
from app.modules.website_analysis.schemas import WebsiteAnalysisRead
from app.modules.website_analysis.service import get_latest_analysis

router = APIRouter(prefix="/companies", tags=["companies"])


async def _get_company_or_404(db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID):
    company = await get_company(db, tenant_id, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.get("", response_model=list[CompanyRead])
async def list_companies_endpoint(
    segment: str | None = None,
    city: str | None = None,
    status_filter: CompanyStatus | None = Query(default=None, alias="status"),
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[CompanyRead]:
    companies = await list_companies(db, context.tenant_id, segment, city, status_filter)
    return [CompanyRead.model_validate(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyDetailRead)
async def get_company_endpoint(
    company_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> CompanyDetailRead:
    company = await _get_company_or_404(db, context.tenant_id, company_id)
    sources = await list_sources(db, context.tenant_id, company_id)
    evidence = await list_evidence_for_company(db, context.tenant_id, company_id)
    analysis = await get_latest_analysis(db, context.tenant_id, company_id)
    business = await get_latest_business_analysis(db, context.tenant_id, company_id)
    return CompanyDetailRead(
        **CompanyRead.model_validate(company).model_dump(),
        sources=[CompanySourceRead.model_validate(s) for s in sources],
        evidence=[EvidenceRead.model_validate(e) for e in evidence],
        website_analysis=WebsiteAnalysisRead.model_validate(analysis) if analysis else None,
        business_analysis=BusinessAnalysisRead.model_validate(business) if business else None,
    )


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company_endpoint(
    company_id: uuid.UUID,
    data: CompanyUpdate,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> CompanyRead:
    """Status and/or do_not_contact — e.g. marking a company INVALID after a
    human finds out (a closed business, wrong segment, ...) that free
    discovery data can't detect on its own (see docs/DISCOVERY.md), or
    flagging do_not_contact (spec section 50, respected by messages/service.py
    before any message is generated or sent)."""
    company = await _get_company_or_404(db, context.tenant_id, company_id)
    company = await update_company(db, company, data.status, data.do_not_contact)
    await log_event(
        db,
        context.tenant_id,
        AuditEventType.COMPANY_UPDATED,
        {
            "company_id": str(company.id),
            "status": company.status.value,
            "do_not_contact": company.do_not_contact,
        },
    )
    await db.commit()
    return CompanyRead.model_validate(company)

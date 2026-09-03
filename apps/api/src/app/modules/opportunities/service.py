import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.companies.models import Company
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity
from app.modules.opportunities.scoring import (
    classify_opportunity,
    compute_components,
    compute_opportunity_score,
    derive_potential_solution,
    determine_opportunity_type,
)


async def get_opportunity_by_company_and_type(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID, opportunity_type: OpportunityType
) -> Opportunity | None:
    result = await db.execute(
        select(Opportunity).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.company_id == company_id,
            Opportunity.type == opportunity_type,
        )
    )
    return result.scalar_one_or_none()


async def score_company(
    db: AsyncSession, tenant_id: uuid.UUID, company: Company, analysis: BusinessAnalysis
) -> tuple[Opportunity, bool]:
    """Deterministic, backend-computed (spec section 40) — no AI call. Reuses
    Business Analysis's already-collected scores/problems rather than
    recomputing or re-asking the AI Analyst (spec section 39 cost control).
    Returns (opportunity, was_created) so callers can log the right audit
    event (spec section 60: opportunity_created vs opportunity_updated)."""
    components = compute_components(
        business_fit_score=analysis.business_fit_score,
        activity_score=analysis.activity_score,
        need_score=analysis.need_score,
    )
    opportunity_type = determine_opportunity_type(analysis.digital_maturity_score)
    opportunity_score = compute_opportunity_score(components)
    classification = classify_opportunity(opportunity_score)
    reasons = list(analysis.problems[:5])
    problem = "; ".join(reasons) if reasons else None
    potential_solution = derive_potential_solution(
        opportunity_type, has_website=bool(company.website)
    )

    existing = await get_opportunity_by_company_and_type(
        db, tenant_id, company.id, opportunity_type
    )
    if existing is not None:
        existing.problem = problem
        existing.potential_solution = potential_solution
        existing.reasons = reasons
        existing.digital_gap = components.digital_gap
        existing.business_fit = components.business_fit
        existing.need = components.need
        existing.commercial_signals = components.commercial_signals
        existing.opportunity_score = opportunity_score
        existing.confidence = analysis.confidence
        existing.classification = classification
        await db.flush()
        return existing, False

    opportunity = Opportunity(
        tenant_id=tenant_id,
        company_id=company.id,
        type=opportunity_type,
        status=OpportunityStatus.OPEN,
        problem=problem,
        potential_solution=potential_solution,
        reasons=reasons,
        digital_gap=components.digital_gap,
        business_fit=components.business_fit,
        need=components.need,
        commercial_signals=components.commercial_signals,
        opportunity_score=opportunity_score,
        confidence=analysis.confidence,
        classification=classification,
    )
    db.add(opportunity)
    await db.flush()
    return opportunity, True


async def list_opportunities(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    segment: str | None = None,
    city: str | None = None,
    status: OpportunityStatus | None = None,
    opportunity_type: OpportunityType | None = None,
    min_score: float | None = None,
    min_confidence: float | None = None,
) -> list[Opportunity]:
    query = select(Opportunity).join(Company, Opportunity.company_id == Company.id).where(
        Opportunity.tenant_id == tenant_id
    )
    if segment is not None:
        query = query.where(Company.segment == segment)
    if city is not None:
        query = query.where(Company.city == city)
    if status is not None:
        query = query.where(Opportunity.status == status)
    else:
        # Default view hides ARCHIVED, same "still worth looking at" default
        # as Company.list_companies hiding INVALID/DUPLICATE.
        query = query.where(Opportunity.status != OpportunityStatus.ARCHIVED)
    if opportunity_type is not None:
        query = query.where(Opportunity.type == opportunity_type)
    if min_score is not None:
        query = query.where(Opportunity.opportunity_score >= min_score)
    if min_confidence is not None:
        query = query.where(Opportunity.confidence >= min_confidence)
    query = query.order_by(Opportunity.opportunity_score.desc().nulls_last())
    result = await db.execute(query)
    return list(result.scalars())


async def get_opportunity(
    db: AsyncSession, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> Opportunity | None:
    result = await db.execute(
        select(Opportunity).where(
            Opportunity.tenant_id == tenant_id, Opportunity.id == opportunity_id
        )
    )
    return result.scalar_one_or_none()


async def update_opportunity_status(
    db: AsyncSession, opportunity: Opportunity, status: OpportunityStatus
) -> Opportunity:
    opportunity.status = status
    await db.flush()
    return opportunity

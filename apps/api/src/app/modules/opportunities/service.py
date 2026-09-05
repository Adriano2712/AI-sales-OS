import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.models import Company
from app.modules.evidence.service import compute_signal_balance, list_evidence_for_company
from app.modules.opportunities.enums import OpportunityOutcome, OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity
from app.modules.opportunities.schemas import OpportunityWeights
from app.modules.opportunities.scoring import (
    DEFAULT_WEIGHTS_V2,
    apply_penalty,
    classify_opportunity,
    compute_components,
    compute_opportunity_confidence,
    compute_opportunity_factors,
    compute_opportunity_score,
    compute_opportunity_score_v2,
    compute_penalties,
    derive_potential_solution,
    determine_opportunity_type,
)
from app.modules.website_analysis.service import get_latest_analysis as get_latest_website_analysis


async def _get_campaign_weights(
    db: AsyncSession, tenant_id: uuid.UUID, company: Company
) -> dict[str, float] | None:
    """Fase 7: mirrors business_analysis/service.py's
    _get_campaign_services — same Company.campaign_run_id ->
    CampaignRun.campaign_id -> Campaign join. None (not an empty dict) when
    there's no campaign context or the campaign never set its own weights —
    compute_opportunity_score_v2 already treats None as "use system
    defaults", so there's no ambiguity to resolve here."""
    if company.campaign_run_id is None:
        return None
    result = await db.execute(
        select(Campaign.opportunity_weights)
        .join(CampaignRun, CampaignRun.campaign_id == Campaign.id)
        .where(CampaignRun.id == company.campaign_run_id, Campaign.tenant_id == tenant_id)
    )
    raw = result.scalar_one_or_none()
    if not raw:
        return None
    return OpportunityWeights(**raw).to_weights_dict()


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
    event (spec section 60: opportunity_created vs opportunity_updated).

    Fase 7 (Opportunity Score 2.0): `digital_gap`/`business_fit`/`need`/
    `commercial_signals` below are the original 4-factor components,
    unchanged — kept as their own columns for API backward-compatibility.
    `opportunity_score`/`confidence` themselves now come from the richer
    Score 2.0 blend (compute_opportunity_score_v2/compute_opportunity_
    confidence), which additionally reads WebsiteAnalysis, Google review
    data, Evidence polarity, and Fase 6's service_fit/buying_potential —
    see compute_opportunity_factors."""
    components = compute_components(
        business_fit_score=analysis.business_fit_score,
        activity_score=analysis.activity_score,
        need_score=analysis.need_score,
    )
    opportunity_type = determine_opportunity_type(analysis.digital_maturity_score)
    reasons = list(analysis.problems[:5])
    problem = "; ".join(reasons) if reasons else None
    potential_solution = derive_potential_solution(
        opportunity_type, has_website=bool(company.website)
    )

    existing = await get_opportunity_by_company_and_type(
        db, tenant_id, company.id, opportunity_type
    )

    website_analysis = (
        await get_latest_website_analysis(db, tenant_id, company.id) if company.website else None
    )
    evidence_list = await list_evidence_for_company(db, tenant_id, company.id)
    factors = compute_opportunity_factors(
        business_fit_score=analysis.business_fit_score,
        activity_score=analysis.activity_score,
        need_score=analysis.need_score,
        service_fit_score=analysis.service_fit_score,
        buying_potential_score=analysis.buying_potential_score,
        website_opportunity_score=website_analysis.opportunity_score if website_analysis else None,
        has_google_reviews=company.google_review_count is not None,
        evidence_signal_balance=compute_signal_balance(evidence_list),
    )
    weights = await _get_campaign_weights(db, tenant_id, company)
    raw_score = compute_opportunity_score_v2(factors, weights)
    penalty = compute_penalties(
        company_status=company.status,
        do_not_contact=company.do_not_contact,
        existing_outcome=existing.outcome if existing is not None else None,
    )
    opportunity_score = apply_penalty(raw_score, penalty.points)
    classification = classify_opportunity(opportunity_score)
    confidence = compute_opportunity_confidence(analysis.confidence, factors)
    score_components = {
        "factors": asdict(factors),
        "weights_used": weights or dict(DEFAULT_WEIGHTS_V2),
        "raw_score": raw_score,
        "penalty_points": penalty.points,
        "penalty_reasons": penalty.reasons,
        # Original 4-factor formula's result, kept for comparison/rollback
        # visibility — not used by anything, the columns above already carry
        # forward its inputs unchanged.
        "legacy_v1_score": compute_opportunity_score(components),
    }

    if existing is not None:
        existing.problem = problem
        existing.potential_solution = potential_solution
        existing.reasons = reasons
        existing.digital_gap = components.digital_gap
        existing.business_fit = components.business_fit
        existing.need = components.need
        existing.commercial_signals = components.commercial_signals
        existing.opportunity_score = opportunity_score
        existing.confidence = confidence
        existing.classification = classification
        existing.score_components = score_components
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
        confidence=confidence,
        classification=classification,
        score_components=score_components,
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


async def update_opportunity(
    db: AsyncSession,
    opportunity: Opportunity,
    status: OpportunityStatus | None = None,
    outcome: OpportunityOutcome | None = None,
    outcome_notes: str | None = None,
) -> Opportunity:
    """No transition-rule enforcement on either field (same reasoning as
    companies/service.py's update_company) — both are human corrections
    reflecting real-world state, not pipeline-driven transitions."""
    if status is not None:
        opportunity.status = status
    if outcome is not None:
        opportunity.outcome = outcome
    if outcome_notes is not None:
        opportunity.outcome_notes = outcome_notes
    await db.flush()
    return opportunity

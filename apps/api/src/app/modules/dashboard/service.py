import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_gateway.models import AICall
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.campaigns.models import CampaignRun
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.dashboard.schemas import (
    AnalysisMetrics,
    CostMetrics,
    DashboardSummary,
    DiscoveryMetrics,
    EnrichmentMetrics,
    FunnelMetrics,
    OpportunityMetrics,
)
from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
    OpportunityStatus,
)
from app.modules.opportunities.models import Opportunity
from app.modules.website_analysis.models import WebsiteAnalysis


async def get_summary(db: AsyncSession, tenant_id: uuid.UUID) -> DashboardSummary:
    """Tenant-wide aggregate (spec section 83). No new data collection — sums
    counters CampaignRun already tracks and rows Opportunity/AICall already
    store. Funnel counts real Opportunity.outcome values a human has logged
    (see opportunities/enums.py) — send/reply still isn't automated, so this
    is only ever as populated as what's actually been tracked by hand."""
    run_totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(CampaignRun.companies_found), 0),
                func.coalesce(func.sum(CampaignRun.companies_validated), 0),
                func.coalesce(func.sum(CampaignRun.duplicates), 0),
                func.coalesce(func.sum(CampaignRun.enriched), 0),
                func.coalesce(func.sum(CampaignRun.analyzed), 0),
            ).where(CampaignRun.tenant_id == tenant_id)
        )
    ).one()

    classification_rows = (
        await db.execute(
            select(Opportunity.classification, func.count())
            .where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.classification.is_not(None),
            )
            .group_by(Opportunity.classification)
        )
    ).all()
    classification_counts: dict[OpportunityClassification, int] = {
        classification: count for classification, count in classification_rows if classification
    }
    total_opportunities = (
        await db.execute(select(func.count()).where(Opportunity.tenant_id == tenant_id))
    ).scalar_one()

    outcome_rows = (
        await db.execute(
            select(Opportunity.outcome, func.count())
            .where(Opportunity.tenant_id == tenant_id, Opportunity.outcome.is_not(None))
            .group_by(Opportunity.outcome)
        )
    ).all()
    outcome_counts: dict[OpportunityOutcome, int] = {
        outcome: count for outcome, count in outcome_rows if outcome
    }

    cost_totals = (
        await db.execute(
            select(func.coalesce(func.sum(AICall.estimated_cost_usd), 0.0), func.count()).where(
                AICall.tenant_id == tenant_id
            )
        )
    ).one()

    invalid_count = (
        await db.execute(
            select(func.count()).where(
                Company.tenant_id == tenant_id, Company.status == CompanyStatus.INVALID
            )
        )
    ).scalar_one()

    # Fase 12 (Analytics): website_found/not_found counted over every
    # non-duplicate company (a DUPLICATE row is the same real-world business
    # as another row already counted — including it would double-count).
    website_rows = (
        await db.execute(
            select(Company.website.is_not(None), func.count())
            .where(Company.tenant_id == tenant_id, Company.status != CompanyStatus.DUPLICATE)
            .group_by(Company.website.is_not(None))
        )
    ).all()
    website_counts: dict[bool, int] = {has_website: count for has_website, count in website_rows}
    website_found = website_counts.get(True, 0)
    website_not_found = website_counts.get(False, 0)
    enrichment_total = website_found + website_not_found
    success_rate = round(website_found / enrichment_total * 100, 1) if enrichment_total else None

    companies_analyzed = (
        await db.execute(
            select(func.count(func.distinct(BusinessAnalysis.company_id))).where(
                BusinessAnalysis.tenant_id == tenant_id
            )
        )
    ).scalar_one()

    score_averages = (
        await db.execute(
            select(func.avg(WebsiteAnalysis.digital_score)).where(
                WebsiteAnalysis.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    business_fit_average = (
        await db.execute(
            select(func.avg(BusinessAnalysis.business_fit_score)).where(
                BusinessAnalysis.tenant_id == tenant_id
            )
        )
    ).scalar_one()

    approved_count = (
        await db.execute(
            select(func.count()).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.status == OpportunityStatus.APPROVED,
            )
        )
    ).scalar_one()

    total_cost = float(cost_totals[0])
    companies_found = run_totals[0]

    return DashboardSummary(
        discovery=DiscoveryMetrics(
            companies_found=companies_found,
            companies_validated=run_totals[1],
            duplicates=run_totals[2],
            enriched=run_totals[3],
            analyzed=run_totals[4],
            invalid=invalid_count,
        ),
        enrichment=EnrichmentMetrics(
            website_found=website_found,
            website_not_found=website_not_found,
            success_rate=success_rate,
        ),
        analysis=AnalysisMetrics(
            companies_analyzed=companies_analyzed,
            average_digital_score=round(score_averages, 1) if score_averages is not None else None,
            average_business_fit=(
                round(business_fit_average, 1) if business_fit_average is not None else None
            ),
        ),
        opportunities=OpportunityMetrics(
            total=total_opportunities,
            high=classification_counts.get(OpportunityClassification.HIGH, 0),
            good=classification_counts.get(OpportunityClassification.GOOD, 0),
            review=classification_counts.get(OpportunityClassification.REVIEW, 0),
            low=classification_counts.get(OpportunityClassification.LOW, 0),
        ),
        funnel=FunnelMetrics(
            approved=approved_count,
            contacted=outcome_counts.get(OpportunityOutcome.CONTACTED, 0),
            replied=outcome_counts.get(OpportunityOutcome.REPLIED, 0),
            proposal_sent=outcome_counts.get(OpportunityOutcome.PROPOSAL_SENT, 0),
            won=outcome_counts.get(OpportunityOutcome.WON, 0),
            lost=outcome_counts.get(OpportunityOutcome.LOST, 0),
        ),
        cost=CostMetrics(
            total_estimated_cost_usd=round(total_cost, 4),
            ai_calls=cost_totals[1],
            cost_per_company=round(total_cost / companies_found, 4) if companies_found else None,
            cost_per_analysis=(
                round(total_cost / run_totals[4], 4) if run_totals[4] else None
            ),
            cost_per_opportunity=(
                round(total_cost / total_opportunities, 4) if total_opportunities else None
            ),
        ),
    )

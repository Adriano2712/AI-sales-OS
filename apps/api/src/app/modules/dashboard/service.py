import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_gateway.models import AICall
from app.modules.campaigns.models import CampaignRun
from app.modules.dashboard.schemas import (
    CostMetrics,
    DashboardSummary,
    DiscoveryMetrics,
    FunnelMetrics,
    OpportunityMetrics,
)
from app.modules.opportunities.enums import OpportunityClassification, OpportunityOutcome
from app.modules.opportunities.models import Opportunity


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

    return DashboardSummary(
        discovery=DiscoveryMetrics(
            companies_found=run_totals[0],
            companies_validated=run_totals[1],
            duplicates=run_totals[2],
            enriched=run_totals[3],
            analyzed=run_totals[4],
        ),
        opportunities=OpportunityMetrics(
            total=total_opportunities,
            high=classification_counts.get(OpportunityClassification.HIGH, 0),
            good=classification_counts.get(OpportunityClassification.GOOD, 0),
            review=classification_counts.get(OpportunityClassification.REVIEW, 0),
            low=classification_counts.get(OpportunityClassification.LOW, 0),
        ),
        funnel=FunnelMetrics(
            contacted=outcome_counts.get(OpportunityOutcome.CONTACTED, 0),
            replied=outcome_counts.get(OpportunityOutcome.REPLIED, 0),
            proposal_sent=outcome_counts.get(OpportunityOutcome.PROPOSAL_SENT, 0),
            won=outcome_counts.get(OpportunityOutcome.WON, 0),
            lost=outcome_counts.get(OpportunityOutcome.LOST, 0),
        ),
        cost=CostMetrics(
            total_estimated_cost_usd=round(float(cost_totals[0]), 4),
            ai_calls=cost_totals[1],
        ),
    )

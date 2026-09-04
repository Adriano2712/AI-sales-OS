from pydantic import BaseModel


class DiscoveryMetrics(BaseModel):
    """Tenant-wide sums of CampaignRun's own counters (spec section 21) —
    no new collection, just aggregation of what Discovery already tracked."""

    companies_found: int
    companies_validated: int
    duplicates: int
    enriched: int
    analyzed: int


class OpportunityMetrics(BaseModel):
    total: int
    high: int
    good: int
    review: int
    low: int


class FunnelMetrics(BaseModel):
    """Real counts of Opportunity.outcome (spec: never a fabricated zero for
    a stage that could exist but wasn't reached — every count here is a
    human-logged real event, see opportunities/enums.py's OpportunityOutcome).
    Only meaningful once outreach is actually happening outside the system —
    an all-zero funnel means "nothing contacted yet", not "broken"."""

    contacted: int
    replied: int
    proposal_sent: int
    won: int
    lost: int


class CostMetrics(BaseModel):
    """Real numbers from ai_calls (spec sections 38/71), not an estimate."""

    total_estimated_cost_usd: float
    ai_calls: int


class DashboardSummary(BaseModel):
    discovery: DiscoveryMetrics
    opportunities: OpportunityMetrics
    funnel: FunnelMetrics
    cost: CostMetrics

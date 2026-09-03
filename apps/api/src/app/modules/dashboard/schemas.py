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


class CostMetrics(BaseModel):
    """Real numbers from ai_calls (spec sections 38/71), not an estimate."""

    total_estimated_cost_usd: float
    ai_calls: int


class DashboardSummary(BaseModel):
    discovery: DiscoveryMetrics
    opportunities: OpportunityMetrics
    cost: CostMetrics

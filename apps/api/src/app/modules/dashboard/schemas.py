from pydantic import BaseModel


class DiscoveryMetrics(BaseModel):
    """Tenant-wide sums of CampaignRun's own counters (spec section 21) —
    no new collection, just aggregation of what Discovery already tracked."""

    companies_found: int
    companies_validated: int
    duplicates: int
    enriched: int
    analyzed: int
    # Fase 12 (Analytics, spec section 83's "invalid"): Company.status ==
    # INVALID, tenant-wide — real count of Company rows, not a CampaignRun
    # counter (no run-level "invalid" field exists), same tenant-wide
    # aggregation style already used for opportunities/cost below.
    invalid: int


class EnrichmentMetrics(BaseModel):
    """Fase 12 (Analytics, spec section 83). Company.website is the one
    enrichment signal already stored as a plain nullable column — counting
    it directly rather than inventing a separate "attempted" flag nothing
    in the codebase tracks. success_rate is null (not 0.0) when there are no
    non-duplicate companies yet, distinguishing "nothing to measure" from a
    real 0% success rate."""

    website_found: int
    website_not_found: int
    success_rate: float | None


class AnalysisMetrics(BaseModel):
    """Fase 12 (Analytics, spec section 83). Averages are null (not 0.0)
    when no row has been scored yet — same "don't fabricate a zero"
    principle as everywhere else in this module."""

    companies_analyzed: int
    average_digital_score: float | None
    average_business_fit: float | None


class OpportunityMetrics(BaseModel):
    total: int
    high: int
    good: int
    review: int
    low: int


class FunnelMetrics(BaseModel):
    """Real counts of Opportunity.outcome/.status (spec: never a fabricated
    zero for a stage that could exist but wasn't reached — every count here
    is a human-logged real event, see opportunities/enums.py). Only
    meaningful once outreach is actually happening outside the system — an
    all-zero funnel means "nothing contacted yet", not "broken"."""

    approved: int
    contacted: int
    replied: int
    proposal_sent: int
    won: int
    lost: int
    # Fase 12: spec section 83 lists "meetings" alongside contacted/replied/
    # proposals/won/lost, but no OpportunityOutcome value for it exists
    # anywhere in this codebase — no workflow sets one. Always null (never
    # 0) means "not tracked", not "zero meetings happened" (spec section
    # 86: don't invent evidence that isn't there). Typed as int | None
    # (not a frozen None) so a future phase that adds real tracking doesn't
    # need a breaking schema change.
    meetings: int | None = None


class CostMetrics(BaseModel):
    """Real numbers from ai_calls (spec sections 38/71), not an estimate.
    Fase 12 adds the three spec section 83 per-unit breakdowns — each null
    (not 0.0) when its denominator is zero, rather than a divide-by-zero or
    a misleading "$0.00 per company"."""

    total_estimated_cost_usd: float
    ai_calls: int
    cost_per_company: float | None
    cost_per_analysis: float | None
    cost_per_opportunity: float | None


class DashboardSummary(BaseModel):
    discovery: DiscoveryMetrics
    enrichment: EnrichmentMetrics
    analysis: AnalysisMetrics
    opportunities: OpportunityMetrics
    funnel: FunnelMetrics
    cost: CostMetrics

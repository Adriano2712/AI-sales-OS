import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
    OpportunityStatus,
    OpportunityType,
)
from app.modules.opportunities.scoring import DEFAULT_WEIGHTS_V2


class OpportunityWeights(BaseModel):
    """Fase 7: a campaign's override of DEFAULT_WEIGHTS_V2
    (opportunities/scoring.py). Any field left unset falls back to the
    system default rather than silently becoming zero-weight — see
    to_weights_dict(). Bounded [0, 1]; they don't need to sum to 1 since
    compute_opportunity_score_v2 renormalizes over whatever's evaluated."""

    digital_gap: float | None = Field(default=None, ge=0, le=1)
    business_fit: float | None = Field(default=None, ge=0, le=1)
    service_fit: float | None = Field(default=None, ge=0, le=1)
    need: float | None = Field(default=None, ge=0, le=1)
    commercial_signals: float | None = Field(default=None, ge=0, le=1)
    buying_potential: float | None = Field(default=None, ge=0, le=1)
    website_opportunity: float | None = Field(default=None, ge=0, le=1)
    customer_validation: float | None = Field(default=None, ge=0, le=1)
    evidence_signal_balance: float | None = Field(default=None, ge=0, le=1)

    def to_weights_dict(self) -> dict[str, float]:
        overrides = self.model_dump(exclude_none=True)
        return {**DEFAULT_WEIGHTS_V2, **overrides}


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    type: OpportunityType
    status: OpportunityStatus
    problem: str | None
    potential_solution: str | None
    reasons: list[str]
    digital_gap: float | None
    business_fit: float | None
    need: float | None
    commercial_signals: float | None
    opportunity_score: float | None
    confidence: float | None
    # Fase 7: full breakdown behind opportunity_score/confidence — raw
    # per-factor values, the weights actually used (campaign override or
    # DEFAULT_WEIGHTS_V2), and any penalty applied. Debugging/transparency,
    # not itself consumed by any scoring logic.
    score_components: dict
    classification: OpportunityClassification | None
    outcome: OpportunityOutcome | None
    outcome_notes: str | None
    created_at: datetime
    updated_at: datetime


class OpportunityUpdate(BaseModel):
    status: OpportunityStatus | None = None
    # Both optional and independent of `status` — a human logs sales-pipeline
    # progress (spec: this is real-world reality, not a system-driven state)
    # separately from deciding whether the opportunity is still worth working.
    outcome: OpportunityOutcome | None = None
    outcome_notes: str | None = None


class OpportunityDetailRead(OpportunityRead):
    company_name: str
    company_segment: str
    company_city: str
    company_state: str
    company_phone: str | None
    company_website: str | None
    company_email: str | None
    # Spec section 46's dashboard field — computed from `status`, not stored
    # (see opportunities/scoring.py:derive_next_action).
    next_action: str
    # Lets the frontend hide/disable "generate message" without a second
    # request — spec section 50 must be visibly respected, not just enforced
    # server-side.
    company_do_not_contact: bool

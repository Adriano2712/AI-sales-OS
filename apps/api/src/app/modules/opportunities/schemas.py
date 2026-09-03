import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.opportunities.enums import OpportunityClassification, OpportunityStatus, OpportunityType


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
    classification: OpportunityClassification | None
    created_at: datetime
    updated_at: datetime


class OpportunityUpdate(BaseModel):
    status: OpportunityStatus


class OpportunityDetailRead(OpportunityRead):
    company_name: str
    company_segment: str
    company_city: str
    company_state: str
    company_phone: str | None
    company_website: str | None
    # Spec section 46's dashboard field — computed from `status`, not stored
    # (see opportunities/scoring.py:derive_next_action).
    next_action: str
    # Lets the frontend hide/disable "generate message" without a second
    # request — spec section 50 must be visibly respected, not just enforced
    # server-side.
    company_do_not_contact: bool

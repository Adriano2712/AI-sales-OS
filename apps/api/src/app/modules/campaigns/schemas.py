import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus
from app.modules.opportunities.schemas import OpportunityWeights


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    segment: str = Field(min_length=1, max_length=100)
    cities: list[str] = Field(min_length=1)
    state: str = Field(min_length=1, max_length=100)
    country: str = Field(default="BR", min_length=2, max_length=2)
    target_quantity: int = Field(gt=0)
    filters: dict = Field(default_factory=dict)
    services: list[str] = Field(default_factory=list)
    # Fase 7 — None means "use opportunities/scoring.py's system defaults".
    opportunity_weights: OpportunityWeights | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    segment: str | None = Field(default=None, min_length=1, max_length=100)
    cities: list[str] | None = Field(default=None, min_length=1)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    target_quantity: int | None = Field(default=None, gt=0)
    filters: dict | None = None
    services: list[str] | None = None
    opportunity_weights: OpportunityWeights | None = None
    status: CampaignStatus | None = None


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    segment: str
    cities: list[str]
    state: str
    country: str
    target_quantity: int
    filters: dict
    services: list[str]
    opportunity_weights: OpportunityWeights | None
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime


class CampaignRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    started_at: datetime | None
    finished_at: datetime | None
    status: CampaignRunStatus
    companies_found: int
    companies_validated: int
    duplicates: int
    enriched: int
    analyzed: int
    opportunities: int
    errors: list
    created_at: datetime
    updated_at: datetime

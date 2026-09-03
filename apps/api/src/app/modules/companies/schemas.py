import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.business_analysis.schemas import BusinessAnalysisRead
from app.modules.companies.enums import CompanyStatus
from app.modules.evidence.schemas import EvidenceRead
from app.modules.website_analysis.schemas import WebsiteAnalysisRead


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    normalized_name: str
    segment: str
    address: str | None
    city: str
    state: str
    country: str
    phone: str | None
    website: str | None
    status: CompanyStatus
    needs_review: bool
    do_not_contact: bool
    created_at: datetime
    updated_at: datetime


class CompanyUpdate(BaseModel):
    status: CompanyStatus | None = None
    do_not_contact: bool | None = None


class CompanySourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    provider: str
    external_id: str
    source_url: str | None
    collected_at: datetime
    data: dict


class CompanyDetailRead(CompanyRead):
    sources: list[CompanySourceRead]
    evidence: list[EvidenceRead]
    website_analysis: WebsiteAnalysisRead | None
    business_analysis: BusinessAnalysisRead | None

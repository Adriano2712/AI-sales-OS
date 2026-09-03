import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BusinessAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    business_fit_score: float | None
    activity_score: float | None
    digital_maturity_score: float | None
    need_score: float | None
    compatibility_score: float | None
    overall_score: float | None
    confidence: float | None
    findings: list[str]
    problems: list[str]
    analyzed_at: datetime

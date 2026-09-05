import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.website_analysis.enums import WebsiteStatus


class WebsiteAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    website_id: uuid.UUID
    status: WebsiteStatus
    digital_score: float | None
    opportunity_score: float | None
    score_funcionamento: float | None
    score_mobile: float | None
    score_ux: float | None
    score_conversao: float | None
    score_conteudo: float | None
    score_design: float | None
    findings: dict
    analyzed_at: datetime

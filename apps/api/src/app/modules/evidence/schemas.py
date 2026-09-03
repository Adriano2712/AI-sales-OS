import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.evidence.enums import EvidenceConfidence


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    claim: str
    source: str
    source_url: str | None
    collected_at: datetime
    confidence: EvidenceConfidence
    supporting_data: dict

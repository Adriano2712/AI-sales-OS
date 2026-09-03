import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.messages.enums import MessageChannel, MessageStatus


class MessageGenerateRequest(BaseModel):
    channel: MessageChannel


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    opportunity_id: uuid.UUID
    channel: MessageChannel
    status: MessageStatus
    generated_text: str
    sent_at: datetime | None
    response: str | None
    created_at: datetime
    updated_at: datetime


class MessageUpdate(BaseModel):
    text: str | None = None
    status: MessageStatus | None = None
    response: str | None = None

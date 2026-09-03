import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.messages.enums import MessageChannel, MessageStatus


class Message(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """One row per generated draft for an Opportunity. Mutable in place
    (edited text, status transitions) rather than append-only — this is a
    single piece of outreach a human works through DRAFT -> APPROVED/REJECTED
    -> SENT, not a re-runnable analysis snapshot."""

    __tablename__ = "messages"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[MessageChannel] = mapped_column(Enum(MessageChannel, name="message_channel"))
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, name="message_status"), default=MessageStatus.DRAFT
    )
    generated_text: Mapped[str] = mapped_column(String(4000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Free text a human logs manually if a reply comes in — never something
    # this system fetches or invents itself (no real channel integration,
    # spec section 49).
    response: Mapped[str | None] = mapped_column(String(4000), nullable=True)

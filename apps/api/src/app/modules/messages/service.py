import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai_gateway.service import run_ai_task_routed
from app.modules.companies.models import Company
from app.modules.messages.ai_writer import MessageAIOutput, build_ai_request, default_language_for_country
from app.modules.messages.enums import VALID_MESSAGE_STATUS_TRANSITIONS, MessageChannel, MessageStatus
from app.modules.messages.models import Message
from app.modules.opportunities.models import Opportunity


class CompanyDoNotContact(ValueError):
    """Raised when generation or send is attempted for a company flagged
    do_not_contact (spec section 50 — the system must respect this, not just
    display it)."""


class InvalidMessageStatusTransition(ValueError):
    def __init__(self, current: MessageStatus, new: MessageStatus) -> None:
        super().__init__(f"Cannot transition message from {current} to {new}")


class MessageNotEditable(ValueError):
    """Text can only be edited while a message is still DRAFT — once
    APPROVED, the approved text is what's meant to be sent."""


def validate_message_status_transition(current: MessageStatus, new: MessageStatus) -> None:
    """Pure function, no DB — unit-testable in isolation (spec section 68:
    state transitions belong in unit tests), same pattern as
    campaigns/service.py's validate_status_transition."""
    if new == current:
        return
    if new not in VALID_MESSAGE_STATUS_TRANSITIONS[current]:
        raise InvalidMessageStatusTransition(current, new)


async def get_existing_draft_or_approved(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    channel: MessageChannel,
    language: str,
) -> Message | None:
    result = await db.execute(
        select(Message).where(
            Message.tenant_id == tenant_id,
            Message.opportunity_id == opportunity_id,
            Message.channel == channel,
            Message.language == language,
            Message.status.in_([MessageStatus.DRAFT, MessageStatus.APPROVED]),
        )
    )
    return result.scalar_one_or_none()


async def generate_message(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    opportunity: Opportunity,
    company: Company,
    channel: MessageChannel,
    language: str | None = None,
) -> Message:
    """Cost control (spec section 39), same idempotent-by-default pattern as
    Fase 5's analyze_business: a non-terminal (DRAFT/APPROVED) message for
    this exact (opportunity, channel, language) is reused instead of calling
    the AI again. Regenerating an already-REJECTED/SENT message, or asking
    for a different language, is a distinct, explicit action — never
    silently returns a draft written in the other language.

    `language=None` defaults from the company's own country (see
    ai_writer.default_language_for_country) rather than always assuming
    Portuguese — real finding: this system's messages used to fabricate a
    Brazilian identity even for companies outside Brazil."""
    if company.do_not_contact:
        raise CompanyDoNotContact(f"Company {company.id} is flagged do_not_contact")

    effective_language = language or default_language_for_country(company.country)

    existing = await get_existing_draft_or_approved(
        db, tenant_id, opportunity.id, channel, effective_language
    )
    if existing is not None:
        return existing

    settings = get_settings()
    ai_request = build_ai_request(
        company_name=company.name,
        segment=company.segment,
        city=company.city,
        problem=opportunity.problem,
        potential_solution=opportunity.potential_solution,
        reasons=opportunity.reasons,
        sender_name=settings.sender_company_name,
        sender_location=settings.sender_company_location,
        language=effective_language,
    )
    ai_response = await run_ai_task_routed(db, tenant_id, ai_request)
    output = cast(MessageAIOutput, ai_response.output)

    message = Message(
        tenant_id=tenant_id,
        opportunity_id=opportunity.id,
        channel=channel,
        status=MessageStatus.DRAFT,
        language=effective_language,
        generated_text=output.text,
    )
    db.add(message)
    await db.flush()
    return message


async def list_messages_for_opportunity(
    db: AsyncSession, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.tenant_id == tenant_id, Message.opportunity_id == opportunity_id)
        .order_by(Message.created_at.desc())
    )
    return list(result.scalars())


async def get_message(db: AsyncSession, tenant_id: uuid.UUID, message_id: uuid.UUID) -> Message | None:
    result = await db.execute(
        select(Message).where(Message.tenant_id == tenant_id, Message.id == message_id)
    )
    return result.scalar_one_or_none()


async def update_message(
    db: AsyncSession,
    message: Message,
    company: Company,
    *,
    text: str | None = None,
    status: MessageStatus | None = None,
    response: str | None = None,
) -> Message:
    if text is not None:
        if message.status != MessageStatus.DRAFT:
            raise MessageNotEditable(f"Cannot edit text of a {message.status.value} message")
        message.generated_text = text

    if status is not None and status != message.status:
        validate_message_status_transition(message.status, status)
        if status == MessageStatus.SENT and company.do_not_contact:
            raise CompanyDoNotContact(f"Company {company.id} is flagged do_not_contact")
        message.status = status
        if status == MessageStatus.SENT:
            message.sent_at = datetime.now(UTC)

    if response is not None:
        message.response = response

    await db.flush()
    return message

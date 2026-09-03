import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.companies.service import get_company
from app.modules.jobs.enums import JobType
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job
from app.modules.messages.enums import MessageStatus
from app.modules.messages.schemas import MessageGenerateRequest, MessageRead, MessageUpdate
from app.modules.messages.service import (
    CompanyDoNotContact,
    InvalidMessageStatusTransition,
    MessageNotEditable,
    get_message,
    list_messages_for_opportunity,
    update_message,
)
from app.modules.opportunities.service import get_opportunity
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db, require_write_access
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(tags=["messages"])


@router.post(
    "/opportunities/{opportunity_id}/messages",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_message_endpoint(
    opportunity_id: uuid.UUID,
    data: MessageGenerateRequest,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Human-triggered, never automatic (spec section 39/47) — this is the
    one job type in the pipeline no other job enqueues on its own. Queued
    like every other AI-call job rather than run inline, so a slow Anthropic
    call never blocks the request."""
    opportunity = await get_opportunity(db, context.tenant_id, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    company = await get_company(db, context.tenant_id, opportunity.company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    if company.do_not_contact:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company is flagged do_not_contact",
        )

    idempotency_key = f"{opportunity_id}-{data.channel.value}"
    job = await get_or_create_job(
        db,
        tenant_id=context.tenant_id,
        job_type=JobType.MESSAGE_GENERATION,
        idempotency_key=idempotency_key,
        payload={"opportunity_id": str(opportunity_id), "channel": data.channel.value},
    )
    await db.commit()
    get_queue().enqueue(
        "app.modules.jobs.handlers.message_generation.run",
        str(job.id),
        str(context.tenant_id),
        str(opportunity_id),
        data.channel.value,
    )
    return {"job_id": str(job.id), "status": "queued"}


@router.get("/opportunities/{opportunity_id}/messages", response_model=list[MessageRead])
async def list_messages_endpoint(
    opportunity_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[MessageRead]:
    opportunity = await get_opportunity(db, context.tenant_id, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    messages = await list_messages_for_opportunity(db, context.tenant_id, opportunity_id)
    return [MessageRead.model_validate(m) for m in messages]


@router.patch("/messages/{message_id}", response_model=MessageRead)
async def update_message_endpoint(
    message_id: uuid.UUID,
    data: MessageUpdate,
    context: TenantContext = Depends(require_write_access()),
    db: AsyncSession = Depends(get_tenant_db),
) -> MessageRead:
    message = await get_message(db, context.tenant_id, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    opportunity = await get_opportunity(db, context.tenant_id, message.opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    company = await get_company(db, context.tenant_id, opportunity.company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    try:
        message = await update_message(
            db, message, company, text=data.text, status=data.status, response=data.response
        )
    except InvalidMessageStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MessageNotEditable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CompanyDoNotContact as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if data.status == MessageStatus.APPROVED:
        await log_event(
            db, context.tenant_id, AuditEventType.MESSAGE_APPROVED, {"message_id": str(message.id)}
        )
    elif data.status == MessageStatus.SENT:
        await log_event(
            db, context.tenant_id, AuditEventType.CONTACTED, {"message_id": str(message.id)}
        )
    if data.response is not None:
        await log_event(
            db,
            context.tenant_id,
            AuditEventType.RESPONSE_RECEIVED,
            {"message_id": str(message.id)},
        )

    await db.commit()
    return MessageRead.model_validate(message)

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.ai_gateway.router import ProviderNotConfigured, get_provider_for_task
from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.models import Job
from app.modules.jobs.service import mark_completed, mark_failed, mark_running
from app.modules.messages.enums import MessageChannel, MessageStatus
from app.modules.messages.models import Message
from app.modules.messages.service import CompanyDoNotContact, generate_message, update_message
from app.modules.notifications.gmail_draft import GmailDraftError, create_gmail_draft
from app.modules.opportunities.models import Opportunity

logger = get_logger(job_type="MESSAGE_GENERATION")


async def _auto_approve_and_draft(
    db: AsyncSession, tenant_id: uuid.UUID, message: Message, company: Company
) -> None:
    """Fase 16 (daily-automation planning): message generation is now
    triggered automatically by scoring.py, not just by a human clicking
    "gerar mensagem" — but sending stays exactly as manual as it always
    was (spec section 39/47). Auto-approving and creating the Gmail draft
    here does not cross that line: a Gmail draft is still nothing more than
    an unsent, editable message sitting in the operator's own Drafts
    folder, identical in effect to what a human already got by clicking
    "aprovar" then "criar rascunho no Gmail" through the UI — the actual
    send is still a deliberate click the operator makes themselves, outside
    this system, same as before. Only reachable for EMAIL: WhatsApp/
    LinkedIn/phone have no equivalent "draft mailbox" to place an unsent
    message into, so those channels are left as-is (DRAFT, awaiting the
    existing manual review flow) rather than silently skipped without a
    trace.

    Any failure here (missing email, Gmail not configured, IMAP error) is
    caught and logged, never raised — the message itself was already
    generated successfully and that must not be lost or retried over a
    drafting step that's explicitly a bonus, not the job's core purpose."""
    if message.channel != MessageChannel.EMAIL:
        return
    if not company.email:
        logger.info(
            "auto_draft_skipped_no_email", message_id=str(message.id), company_id=str(company.id)
        )
        return

    settings = get_settings()
    if not (settings.gmail_smtp_user and settings.gmail_smtp_app_password):
        logger.info("auto_draft_skipped_gmail_not_configured", message_id=str(message.id))
        return

    try:
        await update_message(db, message, company, status=MessageStatus.APPROVED)
        await log_event(
            db, tenant_id, AuditEventType.MESSAGE_APPROVED, {"message_id": str(message.id)}
        )
        await db.commit()

        subject = (
            f"Regarding {company.name}'s online presence"
            if message.language == "en"
            else f"Sobre a presença digital de {company.name}"
        )
        await asyncio.to_thread(
            create_gmail_draft,
            settings.gmail_smtp_user,
            settings.gmail_smtp_app_password,
            company.email,
            subject,
            message.generated_text,
        )
        await log_event(
            db,
            tenant_id,
            AuditEventType.EMAIL_DRAFT_CREATED,
            {"message_id": str(message.id), "company_email": company.email},
        )
        await db.commit()
        logger.info("auto_draft_created", message_id=str(message.id), company_id=str(company.id))
    except GmailDraftError as exc:
        await db.rollback()
        logger.error("auto_draft_failed", message_id=str(message.id), error=str(exc))


async def _run(job_id: str, tenant_id: str, opportunity_id: str, channel: str, language: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    job_uuid = uuid.UUID(job_id)
    opportunity_uuid = uuid.UUID(opportunity_id)
    channel_enum = MessageChannel(channel)

    try:
        get_provider_for_task("message_generation")
    except ProviderNotConfigured:
        logger.error("message_generation_no_api_key", opportunity_id=opportunity_id)
        return

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)
        job = await db.get(Job, job_uuid)
        opportunity = await db.get(Opportunity, opportunity_uuid)
        if job is None or opportunity is None:
            logger.error(
                "message_generation_job_or_opportunity_not_found",
                job_id=job_id,
                opportunity_id=opportunity_id,
            )
            return
        company = await db.get(Company, opportunity.company_id)
        if company is None:
            logger.error("message_generation_company_not_found", opportunity_id=opportunity_id)
            return

        await mark_running(db, job)
        await db.commit()

        try:
            await set_tenant_context(db, tenant_uuid)
            message = await generate_message(
                db, tenant_uuid, opportunity, company, channel_enum, language=language
            )
            await log_event(
                db,
                tenant_uuid,
                AuditEventType.MESSAGE_GENERATED,
                {"message_id": str(message.id), "opportunity_id": opportunity_id},
            )
            await db.commit()

            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_completed(db, job, result={"message_id": str(message.id)})
                await db.commit()

            await set_tenant_context(db, tenant_uuid)
            await _auto_approve_and_draft(db, tenant_uuid, message, company)
        except CompanyDoNotContact as exc:
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_failed(db, job, error=str(exc), retryable=False)
                await db.commit()
            logger.error("message_generation_do_not_contact", opportunity_id=opportunity_id)
        except Exception as exc:  # noqa: BLE001 - a provider/schema failure shouldn't crash the worker
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_failed(db, job, error=str(exc), retryable=True)
                await db.commit()
            logger.error("message_generation_failed", opportunity_id=opportunity_id, error=str(exc))


def run(job_id: str, tenant_id: str, opportunity_id: str, channel: str, language: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    the other job handlers."""
    run_job_sync(_run(job_id, tenant_id, opportunity_id, channel, language))

import uuid

from app.core.config import get_settings
from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.ai_gateway.anthropic_provider import AnthropicProvider
from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.models import Job
from app.modules.jobs.service import mark_completed, mark_failed, mark_running
from app.modules.messages.enums import MessageChannel
from app.modules.messages.service import CompanyDoNotContact, generate_message
from app.modules.opportunities.models import Opportunity

logger = get_logger(job_type="MESSAGE_GENERATION")


async def _run(job_id: str, tenant_id: str, opportunity_id: str, channel: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    job_uuid = uuid.UUID(job_id)
    opportunity_uuid = uuid.UUID(opportunity_id)
    channel_enum = MessageChannel(channel)

    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.error("message_generation_no_api_key", opportunity_id=opportunity_id)
        return
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)

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
                db, tenant_uuid, opportunity, company, channel_enum, provider
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


def run(job_id: str, tenant_id: str, opportunity_id: str, channel: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    the other job handlers."""
    run_job_sync(_run(job_id, tenant_id, opportunity_id, channel))

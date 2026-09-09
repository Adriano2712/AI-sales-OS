import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.business_analysis.service import get_latest_business_analysis
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.enums import JobType
from app.modules.jobs.models import Job
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job, mark_completed, mark_failed, mark_running
from app.modules.messages.ai_writer import default_language_for_country
from app.modules.messages.enums import MessageChannel
from app.modules.opportunities.enums import OpportunityClassification
from app.modules.opportunities.models import Opportunity
from app.modules.opportunities.service import score_company

logger = get_logger(job_type="SCORING")

# Fase 16 (daily-automation planning): only the two classifications the
# user explicitly wants to spend AI generation cost on unattended — LOW/
# REVIEW opportunities still show up in the daily digest for the record,
# same as always, they just don't get an automatic message drafted.
_AUTO_MESSAGE_CLASSIFICATIONS = frozenset(
    {OpportunityClassification.HIGH, OpportunityClassification.GOOD}
)


async def _maybe_trigger_message_generation(
    db: AsyncSession, tenant_id: uuid.UUID, opportunity: Opportunity, company: Company
) -> None:
    """Human-triggered message generation (spec section 39/47) is still the
    only way to reach a real prospect's inbox — nothing here sends
    anything. This just closes the loop scoring.py already ends at: an
    opportunity worth acting on used to need a human to notice it and click
    "gerar mensagem"; now that first draft is waiting for review already
    generated (and, for EMAIL with a known address, already sitting as an
    unsent Gmail draft — see message_generation.py's _auto_approve_and_draft)
    by the time the daily digest arrives."""
    if company.do_not_contact:
        return
    if opportunity.classification not in _AUTO_MESSAGE_CLASSIFICATIONS:
        return

    language = default_language_for_country(company.country)
    idempotency_key = f"{opportunity.id}-{MessageChannel.EMAIL.value}-{language}"
    job = await get_or_create_job(
        db,
        tenant_id=tenant_id,
        job_type=JobType.MESSAGE_GENERATION,
        idempotency_key=idempotency_key,
        payload={
            "opportunity_id": str(opportunity.id),
            "channel": MessageChannel.EMAIL.value,
            "language": language,
        },
    )
    await db.commit()
    get_queue().enqueue(
        "app.modules.jobs.handlers.message_generation.run",
        str(job.id),
        str(tenant_id),
        str(opportunity.id),
        MessageChannel.EMAIL.value,
        language,
    )


async def _run(job_id: str, tenant_id: str, company_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    job_uuid = uuid.UUID(job_id)
    company_uuid = uuid.UUID(company_id)

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)
        job = await db.get(Job, job_uuid)
        company = await db.get(Company, company_uuid)
        if job is None or company is None:
            logger.error("scoring_job_or_company_not_found", job_id=job_id, company_id=company_id)
            return

        await mark_running(db, job)
        await db.commit()

        try:
            await set_tenant_context(db, tenant_uuid)
            analysis = await get_latest_business_analysis(db, tenant_uuid, company.id)
            if analysis is None:
                raise ValueError("no business analysis found for company — scoring needs one")

            opportunity, was_created = await score_company(db, tenant_uuid, company, analysis)
            await log_event(
                db,
                tenant_uuid,
                AuditEventType.OPPORTUNITY_CREATED if was_created else AuditEventType.OPPORTUNITY_UPDATED,
                {
                    "opportunity_id": str(opportunity.id),
                    "company_id": str(company.id),
                    "opportunity_score": opportunity.opportunity_score,
                    "classification": opportunity.classification.value
                    if opportunity.classification
                    else None,
                },
            )
            await db.commit()

            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_completed(
                    db,
                    job,
                    result={
                        "opportunity_id": str(opportunity.id),
                        "opportunity_score": opportunity.opportunity_score,
                    },
                )
                await db.commit()

            await set_tenant_context(db, tenant_uuid)
            await _maybe_trigger_message_generation(db, tenant_uuid, opportunity, company)
        except Exception as exc:  # noqa: BLE001 - a bad/missing analysis shouldn't crash the worker
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_failed(db, job, error=str(exc), retryable=True)
                await db.commit()
            logger.error("scoring_failed", company_id=company_id, error=str(exc))


def run(job_id: str, tenant_id: str, company_id: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    the other job handlers."""
    run_job_sync(_run(job_id, tenant_id, company_id))

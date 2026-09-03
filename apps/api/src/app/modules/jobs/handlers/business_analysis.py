import uuid

from app.core.config import get_settings
from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.ai_gateway.anthropic_provider import AnthropicProvider
from app.modules.business_analysis.service import analyze_business
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.enums import JobType
from app.modules.jobs.models import Job
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job, mark_completed, mark_failed, mark_running

logger = get_logger(job_type="BUSINESS_ANALYSIS")


async def _run(job_id: str, tenant_id: str, company_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    job_uuid = uuid.UUID(job_id)
    company_uuid = uuid.UUID(company_id)

    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.error("business_analysis_no_api_key", company_id=company_id)
        return
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)
        job = await db.get(Job, job_uuid)
        company = await db.get(Company, company_uuid)
        if job is None or company is None:
            logger.error(
                "business_analysis_job_or_company_not_found",
                job_id=job_id,
                company_id=company_id,
            )
            return

        await mark_running(db, job)
        await db.commit()

        try:
            await set_tenant_context(db, tenant_uuid)
            analysis = await analyze_business(db, tenant_uuid, company, provider)
            await db.commit()

            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_completed(
                    db,
                    job,
                    result={
                        "overall_score": analysis.overall_score,
                        "confidence": analysis.confidence,
                    },
                )
                await db.commit()

            # Opportunity Engine (Fase 6) needs a BusinessAnalysis to score —
            # chained here, the one place a fresh one always exists right
            # after being computed, same pattern as website_analysis.py
            # chaining into this handler.
            await set_tenant_context(db, tenant_uuid)
            scoring_job = await get_or_create_job(
                db,
                tenant_id=tenant_uuid,
                job_type=JobType.SCORING,
                idempotency_key=str(company.id),
                payload={"company_id": str(company.id)},
            )
            await db.commit()
            get_queue().enqueue(
                "app.modules.jobs.handlers.scoring.run",
                str(scoring_job.id),
                str(tenant_uuid),
                str(company.id),
            )
        except Exception as exc:  # noqa: BLE001 - a provider/schema failure shouldn't crash the worker
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_failed(db, job, error=str(exc), retryable=True)
                await db.commit()
            logger.error("business_analysis_failed", company_id=company_id, error=str(exc))


def run(job_id: str, tenant_id: str, company_id: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    the other job handlers."""
    run_job_sync(_run(job_id, tenant_id, company_id))

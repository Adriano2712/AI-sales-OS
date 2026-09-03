import uuid

from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.enums import JobType
from app.modules.jobs.models import Job
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job, mark_completed, mark_failed, mark_running
from app.modules.website_analysis.service import analyze_website

logger = get_logger(job_type="WEBSITE_ANALYSIS")


async def _run(job_id: str, tenant_id: str, company_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    job_uuid = uuid.UUID(job_id)
    company_uuid = uuid.UUID(company_id)

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)
        job = await db.get(Job, job_uuid)
        company = await db.get(Company, company_uuid)
        if job is None or company is None:
            logger.error(
                "website_analysis_job_or_company_not_found",
                job_id=job_id,
                company_id=company_id,
            )
            return

        await mark_running(db, job)
        await db.commit()

        try:
            await set_tenant_context(db, tenant_uuid)
            analysis = await analyze_website(db, tenant_uuid, company)
            await db.commit()

            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_completed(db, job, result={"digital_score": analysis.digital_score})
                await db.commit()

            # Chained here (not from the discovery job) because this is the
            # point a fresh digital_score actually exists to feed the AI
            # Analyst — see jobs/handlers/discovery.py for the other half of
            # this split (companies with no website skip straight there).
            await set_tenant_context(db, tenant_uuid)
            business_job = await get_or_create_job(
                db,
                tenant_id=tenant_uuid,
                job_type=JobType.BUSINESS_ANALYSIS,
                idempotency_key=str(company.id),
                payload={"company_id": str(company.id)},
            )
            await db.commit()
            get_queue().enqueue(
                "app.modules.jobs.handlers.business_analysis.run",
                str(business_job.id),
                str(tenant_uuid),
                str(company.id),
            )
        except Exception as exc:  # noqa: BLE001 - a slow/broken site shouldn't crash the worker
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                await mark_failed(db, job, error=str(exc), retryable=True)
                await db.commit()
            logger.error("website_analysis_failed", company_id=company_id, error=str(exc))


def run(job_id: str, tenant_id: str, company_id: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    handlers/ping.py and handlers/discovery.py."""
    run_job_sync(_run(job_id, tenant_id, company_id))

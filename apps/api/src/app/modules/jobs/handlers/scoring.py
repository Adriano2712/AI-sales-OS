import uuid

from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.business_analysis.service import get_latest_business_analysis
from app.modules.companies.models import Company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.models import Job
from app.modules.jobs.service import mark_completed, mark_failed, mark_running
from app.modules.opportunities.service import score_company

logger = get_logger(job_type="SCORING")


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

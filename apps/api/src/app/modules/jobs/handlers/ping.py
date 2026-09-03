import uuid

from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.models import Job
from app.modules.jobs.service import mark_completed, mark_failed, mark_running

logger = get_logger(job_type="PING")


async def _run(job_id: str, tenant_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)

        job = await db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.error("ping_job_not_found", job_id=job_id)
            return

        await mark_running(db, job)
        await db.commit()

        try:
            await set_tenant_context(db, tenant_uuid)
            await mark_completed(db, job, result={"pong": True})
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - smoke-test job: log, mark failed, don't raise
            await db.rollback()
            await set_tenant_context(db, tenant_uuid)
            failed_job = await db.get(Job, uuid.UUID(job_id))
            if failed_job is not None:
                await mark_failed(db, failed_job, error=str(exc), retryable=False)
                await db.commit()
            logger.error("ping_job_failed", job_id=job_id, error=str(exc))


def run(job_id: str, tenant_id: str) -> None:
    """RQ entrypoint. RQ workers invoke plain sync callables, so this bridges into
    the app's async DB layer for the single job it's given — proves the
    API -> Redis -> worker -> DB round-trip end to end (Phase 0 infra smoke test).
    """
    run_job_sync(_run(job_id, tenant_id))

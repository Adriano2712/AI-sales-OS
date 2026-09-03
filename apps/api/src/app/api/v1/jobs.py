from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/ping", response_model=dict)
async def enqueue_ping_job(
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Phase 0 infra smoke test: proves API -> DB -> Redis -> worker -> DB works
    end-to-end. Remove once a real job type exercises the same path."""
    job = await get_or_create_job(
        db,
        tenant_id=context.tenant_id,
        job_type=JobType.PING,
        idempotency_key="manual-ping",
    )
    await db.commit()

    if job.status in (JobStatus.PENDING, JobStatus.RETRYING):
        get_queue().enqueue(
            "app.modules.jobs.handlers.ping.run", str(job.id), str(context.tenant_id)
        )

    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/{job_id}", response_model=dict)
async def get_job(
    job_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    job = await db.get(Job, job_id)
    if job is None:
        return {"error": "not found"}
    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "result": job.result,
        "error": job.error,
        "attempts": job.attempts,
    }

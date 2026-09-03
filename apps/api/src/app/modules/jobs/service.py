import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job


async def get_or_create_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_type: JobType,
    idempotency_key: str,
    payload: dict | None = None,
) -> Job:
    """Returns the existing job for (tenant, type, idempotency_key) if present,
    otherwise creates a new PENDING one. Callers must re-enqueue on the *existing*
    job only if it's in a retryable state — this function does not decide that."""
    result = await db.execute(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.type == job_type,
            Job.idempotency_key == idempotency_key,
        )
    )
    job = result.scalar_one_or_none()
    if job is not None:
        return job

    job = Job(
        tenant_id=tenant_id,
        type=job_type,
        idempotency_key=idempotency_key,
        payload=payload or {},
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.flush()
    return job


async def mark_running(db: AsyncSession, job: Job) -> Job:
    job.status = JobStatus.RUNNING
    job.attempts += 1
    await db.flush()
    return job


async def mark_completed(db: AsyncSession, job: Job, result: dict | None = None) -> Job:
    job.status = JobStatus.COMPLETED
    job.result = result or {}
    job.error = None
    await db.flush()
    return job


async def mark_failed(db: AsyncSession, job: Job, error: str, retryable: bool) -> Job:
    job.status = JobStatus.RETRYING if retryable else JobStatus.FAILED
    job.error = error
    await db.flush()
    return job

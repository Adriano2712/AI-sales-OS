import pytest

from app.core.db import set_tenant_context
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.service import get_or_create_job, mark_completed, mark_failed, mark_running

from .conftest import requires_live_db


@requires_live_db
@pytest.mark.asyncio
async def test_same_idempotency_key_returns_existing_job(app_session_factory, two_tenants):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        first = await get_or_create_job(
            session, tenant_a.id, JobType.PING, "same-key", payload={"n": 1}
        )
        await session.commit()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        second = await get_or_create_job(
            session, tenant_a.id, JobType.PING, "same-key", payload={"n": 2}
        )
        await session.commit()

    assert first.id == second.id
    assert second.payload == {"n": 1}, "re-running with the same key must not overwrite the job"


@requires_live_db
@pytest.mark.asyncio
async def test_status_transitions_persist(app_session_factory, two_tenants):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = await get_or_create_job(session, tenant_a.id, JobType.PING, "status-key")
        await session.commit()
        job_id = job.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = await session.get(job.__class__, job_id)
        await mark_running(session, job)
        await session.commit()
        assert job.status == JobStatus.RUNNING
        assert job.attempts == 1

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = await session.get(job.__class__, job_id)
        await mark_completed(session, job, result={"ok": True})
        await session.commit()
        assert job.status == JobStatus.COMPLETED
        assert job.result == {"ok": True}


@requires_live_db
@pytest.mark.asyncio
async def test_failed_job_marked_retrying_when_retryable(app_session_factory, two_tenants):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = await get_or_create_job(session, tenant_a.id, JobType.PING, "retry-key")
        await mark_failed(session, job, error="timeout", retryable=True)
        await session.commit()

        assert job.status == JobStatus.RETRYING
        assert job.error == "timeout"

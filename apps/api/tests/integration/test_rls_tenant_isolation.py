import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context, set_user_context
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job

from .conftest import requires_live_db


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_job(app_session_factory, two_tenants):
    """The core claim of spec section 18/70: tenant isolation is enforced by the
    database, not just by the query the app happens to write."""
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.PING,
            status=JobStatus.PENDING,
            idempotency_key="rls-read-test",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        fetched = await session.get(Job, job_id)
        assert fetched is None, "tenant B must not see tenant A's job row"

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        fetched = await session.get(Job, job_id)
        assert fetched is not None
        assert fetched.id == job_id


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_job_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    """WITH CHECK on the tenant_isolation policy — not just SELECT is guarded."""
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_b.id,  # mismatched on purpose
            type=JobType.PING,
            status=JobStatus.PENDING,
            idempotency_key="rls-write-check-test",
        )
        session.add(job)
        with pytest.raises(DBAPIError):
            await session.commit()


@requires_live_db
@pytest.mark.asyncio
async def test_no_tenant_context_hides_all_rows(app_session_factory, two_tenants):
    """A session that never called set_tenant_context (bug elsewhere in the app)
    must fail closed — see nothing — rather than see everything."""
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.PING,
            status=JobStatus.PENDING,
            idempotency_key="rls-no-context-test",
        )
        session.add(job)
        await session.commit()

    async with app_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(Job))
        assert result.scalars().all() == []


@requires_live_db
@pytest.mark.asyncio
async def test_user_only_sees_own_memberships(admin_session, app_session_factory, two_tenants):
    import uuid as uuid_module

    from app.modules.auth.models import User
    from app.modules.tenancy.enums import Role
    from app.modules.tenancy.models import Membership

    tenant_a, tenant_b = two_tenants

    user_1 = User(auth_user_id=uuid_module.uuid4(), email=f"{uuid_module.uuid4().hex}@test.com")
    user_2 = User(auth_user_id=uuid_module.uuid4(), email=f"{uuid_module.uuid4().hex}@test.com")
    admin_session.add_all([user_1, user_2])
    await admin_session.flush()

    membership_1 = Membership(user_id=user_1.id, tenant_id=tenant_a.id, role=Role.ADMIN)
    membership_2 = Membership(user_id=user_2.id, tenant_id=tenant_b.id, role=Role.ADMIN)
    admin_session.add_all([membership_1, membership_2])
    await admin_session.commit()

    try:
        async with app_session_factory() as session:
            from sqlalchemy import select

            await set_user_context(session, user_1.id)
            result = await session.execute(select(Membership))
            visible = result.scalars().all()
            assert [m.id for m in visible] == [membership_1.id]
    finally:
        await admin_session.delete(membership_1)
        await admin_session.delete(membership_2)
        await admin_session.delete(user_1)
        await admin_session.delete(user_2)
        await admin_session.commit()

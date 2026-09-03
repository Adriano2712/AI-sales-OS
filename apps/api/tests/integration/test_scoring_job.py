import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import set_tenant_context
from app.modules.audit.models import AuditLog
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job
from app.modules.opportunities.enums import OpportunityClassification, OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import ADMIN_DATABASE_URL, requires_live_db


@requires_live_db
@pytest.mark.asyncio
async def test_scoring_job_creates_opportunity_from_business_analysis(app_session_factory):
    import app.modules.jobs.handlers.scoring as handler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scoring Job Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Sem Site Para Scoring",
                normalized_name="restaurante sem site para scoring",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                phone="1533335555",
                website=None,
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()

            # digital_maturity_score=0 (no website) -> a real, low-digital-
            # maturity BusinessAnalysis, same shape analyze_business would
            # have produced.
            analysis = BusinessAnalysis(
                tenant_id=tenant_id,
                company_id=company.id,
                business_fit_score=70.0,
                activity_score=66.7,
                digital_maturity_score=0.0,
                need_score=100.0,
                compatibility_score=60.0,
                overall_score=62.0,
                confidence=55.0,
                findings=["Some finding."],
                problems=["No website found.", "No online booking."],
                analyzed_at=datetime.now(UTC),
            )
            session.add(analysis)
            await session.flush()

            job = Job(
                tenant_id=tenant_id,
                type=JobType.SCORING,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            opp_result = await session.execute(
                select(Opportunity).where(Opportunity.company_id == company_id)
            )
            opportunity = opp_result.scalar_one()
            assert opportunity.type == OpportunityType.WEBSITE  # low digital_maturity_score
            assert opportunity.status == OpportunityStatus.OPEN
            assert opportunity.digital_gap == 100.0
            assert opportunity.business_fit == 70.0
            assert opportunity.commercial_signals == 66.7
            assert opportunity.opportunity_score is not None
            assert opportunity.confidence == 55.0
            assert opportunity.classification in (
                OpportunityClassification.HIGH,
                OpportunityClassification.GOOD,
                OpportunityClassification.REVIEW,
                OpportunityClassification.LOW,
            )
            assert "No website found." in opportunity.reasons
            assert opportunity.potential_solution is not None

            updated_job = await session.get(Job, job_id)
            assert updated_job.status == JobStatus.COMPLETED

            audit_result = await session.execute(
                select(AuditLog).where(AuditLog.event_type == "opportunity_created")
            )
            assert audit_result.scalar_one_or_none() is not None
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_rerunning_scoring_updates_the_same_opportunity_row(app_session_factory):
    """Idempotency (spec section 54): rerunning SCORING for the same company
    must update the existing Opportunity, not create a second one."""
    import app.modules.jobs.handlers.scoring as handler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scoring Rerun Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Rerun Scoring",
                normalized_name="restaurante rerun scoring",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()

            analysis = BusinessAnalysis(
                tenant_id=tenant_id,
                company_id=company.id,
                business_fit_score=50.0,
                activity_score=50.0,
                digital_maturity_score=0.0,
                need_score=100.0,
                compatibility_score=50.0,
                overall_score=50.0,
                confidence=50.0,
                findings=[],
                problems=["Problem A."],
                analyzed_at=datetime.now(UTC),
            )
            session.add(analysis)
            await session.flush()

            job1 = Job(
                tenant_id=tenant_id,
                type=JobType.SCORING,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job1)
            await session.commit()
            company_id, job1_id = company.id, job1.id

        await handler._run(str(job1_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job2 = Job(
                tenant_id=tenant_id,
                type=JobType.SCORING,
                status=JobStatus.PENDING,
                idempotency_key=f"{company_id}-retry",
            )
            session.add(job2)
            await session.commit()
            job2_id = job2.id

        await handler._run(str(job2_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            opp_result = await session.execute(
                select(Opportunity).where(Opportunity.company_id == company_id)
            )
            opportunities = opp_result.scalars().all()
            assert len(opportunities) == 1  # updated in place, not duplicated
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

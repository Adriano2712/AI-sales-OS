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


class _FakeQueue:
    """Same pattern as test_scheduler.py's own _FakeQueue -- scoring.py now
    chains into MESSAGE_GENERATION for HIGH/GOOD opportunities (see
    jobs/handlers/scoring.py's _maybe_trigger_message_generation), and
    without this every test reaching that classification would enqueue a
    real job against the real shared Redis, referencing a throwaway test
    tenant that's about to be deleted -- confirmed the hard way: a real run
    of this exact test file left 2 stale message_generation jobs (plus 2
    stale scoring jobs from business_analysis's own pre-existing,
    similarly-unmocked chaining) sitting in the real queue."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(self, *args) -> None:
        self.calls.append(args)


@requires_live_db
@pytest.mark.asyncio
async def test_scoring_job_creates_opportunity_from_business_analysis(app_session_factory, monkeypatch):
    import app.modules.jobs.handlers.scoring as handler

    monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

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
            # Legacy 4-factor components — unchanged by Fase 7, still their
            # own columns for API backward-compatibility.
            assert opportunity.digital_gap == 100.0
            assert opportunity.business_fit == 70.0
            assert opportunity.commercial_signals == 66.7
            # Fase 7 (Opportunity Score 2.0): only 4 of 9 factors are
            # evaluable here (no website, no campaign, no evidence, no
            # Google reviews, no service_fit/buying_potential on this
            # BusinessAnalysis) — real value confirmed against a live run
            # with this exact scenario (see docs/OPPORTUNITIES.md).
            assert opportunity.opportunity_score == 77.7
            assert opportunity.classification == OpportunityClassification.GOOD
            # OPPORTUNITY_CONFIDENCE is no longer a naive pass-through of
            # BusinessAnalysis.confidence (55.0) — it's scaled by how much
            # of the Score 2.0 factor set was actually known (4 of 9 here).
            assert opportunity.confidence == round(55.0 * (4 / 9), 1)
            assert "No website found." in opportunity.reasons
            assert opportunity.potential_solution is not None

            # Fase 7: full breakdown is persisted for transparency/debugging.
            assert opportunity.score_components["factors"]["digital_gap"] == 100.0
            assert opportunity.score_components["factors"]["service_fit"] is None
            assert opportunity.score_components["penalty_points"] == 0.0
            assert opportunity.score_components["penalty_reasons"] == []

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
async def test_rerunning_scoring_updates_the_same_opportunity_row(app_session_factory, monkeypatch):
    """Idempotency (spec section 54): rerunning SCORING for the same company
    must update the existing Opportunity, not create a second one."""
    import app.modules.jobs.handlers.scoring as handler

    monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

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


@requires_live_db
@pytest.mark.asyncio
async def test_invalid_and_do_not_contact_company_gets_penalized_to_zero(app_session_factory, monkeypatch):
    """Fase 7 penalties, end to end: an apparently-closed (INVALID) business
    marked do-not-contact must never surface as a fresh, workable
    opportunity — spec's own negative examples, applied for real."""
    import app.modules.jobs.handlers.scoring as handler

    monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scoring Penalty Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Fechado E Nao Contatar",
                normalized_name="restaurante fechado e nao contatar",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                status=CompanyStatus.INVALID,
                do_not_contact=True,
            )
            session.add(company)
            await session.flush()

            analysis = BusinessAnalysis(
                tenant_id=tenant_id,
                company_id=company.id,
                business_fit_score=90.0,
                activity_score=90.0,
                digital_maturity_score=0.0,
                need_score=100.0,
                compatibility_score=90.0,
                overall_score=90.0,
                confidence=90.0,
                findings=[],
                problems=[],
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
            # A raw score this high (mostly-known, mostly-positive factors)
            # would otherwise be GOOD/HIGH — the penalty must dominate.
            assert opportunity.score_components["raw_score"] > 80.0
            assert opportunity.score_components["penalty_points"] == 90.0
            assert "Company status is INVALID" in opportunity.score_components["penalty_reasons"]
            assert "Company is marked do-not-contact" in opportunity.score_components["penalty_reasons"]
            assert opportunity.opportunity_score == 0.0  # clipped, never negative
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_campaign_weight_override_changes_the_opportunity_score(app_session_factory, monkeypatch):
    """Fase 7's "weights configurable per campaign" requirement, end to end:
    a campaign that only cares about business_fit must score purely on
    that dimension for a company discovered through it."""
    import app.modules.jobs.handlers.scoring as handler
    from app.modules.campaigns.enums import CampaignStatus
    from app.modules.campaigns.models import Campaign, CampaignRun

    monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scoring Weights Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            campaign = Campaign(
                tenant_id=tenant_id,
                name="Campanha Peso Customizado",
                segment="restaurants",
                cities=["Sorocaba"],
                state="SP",
                country="BR",
                target_quantity=5,
                opportunity_weights={
                    "business_fit": 1.0,
                    "digital_gap": 0.0,
                    "need": 0.0,
                    "commercial_signals": 0.0,
                    "service_fit": 0.0,
                    "buying_potential": 0.0,
                    "website_opportunity": 0.0,
                    "customer_validation": 0.0,
                    "evidence_signal_balance": 0.0,
                },
                status=CampaignStatus.ACTIVE,
            )
            session.add(campaign)
            await session.flush()
            run = CampaignRun(tenant_id=tenant_id, campaign_id=campaign.id)
            session.add(run)
            await session.flush()

            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Peso Customizado",
                normalized_name="restaurante peso customizado",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                status=CompanyStatus.DISCOVERED,
                campaign_run_id=run.id,
            )
            session.add(company)
            await session.flush()

            analysis = BusinessAnalysis(
                tenant_id=tenant_id,
                company_id=company.id,
                business_fit_score=100.0,
                activity_score=0.0,
                digital_maturity_score=100.0,
                need_score=0.0,
                compatibility_score=50.0,
                overall_score=50.0,
                confidence=80.0,
                findings=[],
                problems=[],
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
            # need/digital_gap are both 0 (great digital maturity, no
            # need) — with default weights this would drag the score way
            # down. The campaign's override makes business_fit (100) the
            # only thing that counts.
            assert opportunity.opportunity_score == 100.0
            assert opportunity.score_components["weights_used"]["business_fit"] == 1.0
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

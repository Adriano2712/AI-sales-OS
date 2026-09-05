import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import set_tenant_context
from app.modules.ai_gateway.base import AIProvider, AIRequest, AIResponse
from app.modules.business_analysis.ai_analyst import BusinessAnalysisAIOutput
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.evidence.enums import EvidencePolarity
from app.modules.evidence.models import Evidence
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job

from .conftest import ADMIN_DATABASE_URL, requires_live_db


class _FakeAIProvider(AIProvider):
    """Stands in for AnthropicProvider — automated tests must never spend
    real money (spec section 39). Real-world interop is verified separately,
    once, by hand — see docs/BUSINESS_ANALYSIS.md."""

    name = "fake"

    async def generate(self, request: AIRequest) -> AIResponse:
        output = BusinessAnalysisAIOutput(
            business_fit_score=70,
            compatibility_score=60,
            confidence=55,
            findings=["Test finding about the company."],
            problems=["Test problem identified."],
        )
        return AIResponse(
            output=output,
            raw_text=output.model_dump_json(),
            provider=self.name,
            model="fake-model",
            tokens_input=100,
            tokens_output=50,
            latency_ms=1,
            estimated_cost_usd=0.0,
        )


@requires_live_db
@pytest.mark.asyncio
async def test_business_analysis_job_creates_analysis_and_evidence(
    app_session_factory, monkeypatch
):
    import app.modules.jobs.handlers.business_analysis as handler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Business Analysis Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Sem Site",
                normalized_name="restaurante sem site",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                phone="1533334444",
                website=None,
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()
            job = Job(
                tenant_id=tenant_id,
                type=JobType.BUSINESS_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        # Two seams to patch since Fase 2's Model Router: the handler's own
        # preflight check (get_provider_for_task, imported directly), and
        # the one ai_gateway.service.run_ai_task_routed actually calls to
        # answer the request. Both must return the fake, or the preflight
        # passes but a real Anthropic call still fires (or vice versa).
        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _FakeAIProvider()  # noqa: E731
        monkeypatch.setattr(handler, "get_provider_for_task", fake_router)
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            analysis_result = await session.execute(
                select(BusinessAnalysis).where(BusinessAnalysis.company_id == company_id)
            )
            analysis = analysis_result.scalar_one()
            assert analysis.business_fit_score == 70.0
            assert analysis.compatibility_score == 60.0
            assert analysis.confidence == 55.0
            # No website -> digital_maturity_score deterministically 0,
            # need_score deterministically 100 (see scoring.py).
            assert analysis.digital_maturity_score == 0.0
            assert analysis.need_score == 100.0
            assert analysis.overall_score is not None
            assert analysis.findings == ["Test finding about the company."]
            assert analysis.problems == ["Test problem identified."]

            evidence_result = await session.execute(
                select(Evidence).where(Evidence.company_id == company_id)
            )
            evidence_by_claim = {e.claim: e for e in evidence_result.scalars()}
            assert "Test finding about the company." in evidence_by_claim
            assert "Test problem identified." in evidence_by_claim
            # Opportunity Signal classification (Fase 3): a "problem" is a
            # positive signal by construction (a gap our services could
            # address); a "finding" is a neutral observation.
            assert evidence_by_claim["Test finding about the company."].polarity == EvidencePolarity.NEUTRAL
            assert evidence_by_claim["Test problem identified."].polarity == EvidencePolarity.POSITIVE

            updated_job = await session.get(Job, job_id)
            assert updated_job.status == JobStatus.COMPLETED
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_rerunning_business_analysis_does_not_call_ai_again(
    app_session_factory, monkeypatch
):
    """Cost control (spec section 39): a company already analyzed must not
    trigger a second AI call."""
    import app.modules.jobs.handlers.business_analysis as handler

    call_count = 0

    class _CountingFakeProvider(AIProvider):
        name = "fake"

        async def generate(self, request: AIRequest) -> AIResponse:
            nonlocal call_count
            call_count += 1
            output = BusinessAnalysisAIOutput(
                business_fit_score=50,
                compatibility_score=50,
                confidence=50,
                findings=[],
                problems=[],
            )
            return AIResponse(
                output=output,
                raw_text=output.model_dump_json(),
                provider=self.name,
                model="fake-model",
                tokens_input=10,
                tokens_output=10,
                latency_ms=1,
                estimated_cost_usd=0.0,
            )

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Business Analysis Rerun Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Rerun",
                normalized_name="restaurante rerun",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()
            job1 = Job(
                tenant_id=tenant_id,
                type=JobType.BUSINESS_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job1)
            await session.commit()
            company_id, job1_id = company.id, job1.id

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _CountingFakeProvider()  # noqa: E731
        monkeypatch.setattr(handler, "get_provider_for_task", fake_router)
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

        await handler._run(str(job1_id), str(tenant_id), str(company_id))
        assert call_count == 1

        # Simulate a second, independent job for the same company (e.g. a
        # retry or duplicate enqueue) — must reuse the existing analysis.
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job2 = Job(
                tenant_id=tenant_id,
                type=JobType.BUSINESS_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=f"{company_id}-retry",
            )
            session.add(job2)
            await session.commit()
            job2_id = job2.id

        await handler._run(str(job2_id), str(tenant_id), str(company_id))
        assert call_count == 1  # still 1 — no second AI call
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

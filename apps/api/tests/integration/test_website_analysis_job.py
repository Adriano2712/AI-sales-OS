import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import set_tenant_context
from app.modules.ai_gateway.base import AIProvider, AIRequest, AIResponse
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job
from app.modules.website_analysis.ai_diagnostic import SiteDiagnosticAIOutput
from app.modules.website_analysis.crawler import WebsiteCrawler
from app.modules.website_analysis.models import Website, WebsiteAnalysis, WebsitePage

from .conftest import ADMIN_DATABASE_URL, requires_live_db


class _FakeAIProvider(AIProvider):
    """Stands in for AnthropicProvider — automated tests must never spend
    real money (spec section 39), same discipline as
    test_business_analysis_job.py."""

    name = "fake"

    async def generate(self, request: AIRequest) -> AIResponse:
        output = SiteDiagnosticAIOutput(business_impact="Test business impact paragraph.")
        return AIResponse(
            output=output,
            raw_text=output.model_dump_json(),
            provider=self.name,
            model="fake-model",
            tokens_input=50,
            tokens_output=20,
            latency_ms=1,
            estimated_cost_usd=0.0,
        )

_HOMEPAGE_HTML = """
<html><head>
  <title>Restaurante Mock</title>
  <meta name="description" content="Comida boa">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/style.css">
</head><body>
  <nav>menu</nav>
  <a href="/contato">Contato</a>
  <a href="tel:+551533334444">Ligue</a>
  <p>""" + ("palavra " * 150) + """</p>
</body></html>
"""

_CONTACT_HTML = """
<html><head><title>Contato</title></head>
<body><form action="/send"></form></body></html>
"""


def _mock_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path in ("/", ""):
        return httpx.Response(200, text=_HOMEPAGE_HTML)
    if request.url.path == "/contato":
        return httpx.Response(200, text=_CONTACT_HTML)
    return httpx.Response(404, text="not found")


@requires_live_db
@pytest.mark.asyncio
async def test_website_analysis_job_creates_score_and_pages(app_session_factory, monkeypatch):
    import app.modules.website_analysis.service as website_service

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Website Analysis Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Mock",
                normalized_name="restaurante mock",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite.example",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()

            job = Job(
                tenant_id=tenant_id,
                type=JobType.WEBSITE_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        # Point the crawler at a mock transport — never a real site in
        # automated tests (spec section 31; see docs for the one manual
        # real-site verification).
        mock_transport = httpx.MockTransport(_mock_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _FakeAIProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)

            website_result = await session.execute(
                select(Website).where(Website.company_id == company_id)
            )
            website = website_result.scalar_one()

            pages_result = await session.execute(
                select(WebsitePage).where(WebsitePage.website_id == website.id)
            )
            pages = pages_result.scalars().all()
            assert len(pages) == 2
            assert {p.url for p in pages} == {
                "https://mocksite.example/",
                "https://mocksite.example/contato",
            }

            analysis_result = await session.execute(
                select(WebsiteAnalysis).where(WebsiteAnalysis.website_id == website.id)
            )
            analysis = analysis_result.scalar_one()
            assert analysis.digital_score is not None
            assert analysis.score_funcionamento == 100.0
            assert analysis.score_mobile == 100.0
            # Homepage loaded -> deterministic problems computed and the AI
            # diagnostic paragraph called (via the fake provider above).
            assert isinstance(analysis.findings["problems"], list)
            assert analysis.findings["ai_diagnostic"] == "Test business impact paragraph."

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
async def test_rerunning_analysis_replaces_pages_not_accumulates(
    app_session_factory, monkeypatch
):
    import app.modules.website_analysis.service as website_service

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Website Rerun Test Tenant {uuid.uuid4().hex[:6]}")
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
                website="https://mocksite2.example",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()
            job = Job(
                tenant_id=tenant_id,
                type=JobType.WEBSITE_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        mock_transport = httpx.MockTransport(_mock_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _FakeAIProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        await handler._run(str(job_id), str(tenant_id), str(company_id))
        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            website_result = await session.execute(
                select(Website).where(Website.company_id == company_id)
            )
            website = website_result.scalar_one()

            pages_result = await session.execute(
                select(WebsitePage).where(WebsitePage.website_id == website.id)
            )
            assert len(pages_result.scalars().all()) == 2  # not 4

            analyses_result = await session.execute(
                select(WebsiteAnalysis).where(WebsiteAnalysis.website_id == website.id)
            )
            # website_analyses IS append-only — two runs, two rows.
            assert len(analyses_result.scalars().all()) == 2
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_down_site_gets_deterministic_problem_and_skips_ai_call(
    app_session_factory, monkeypatch
):
    """Cost control (spec section 39): a fully down site's diagnosis is
    already obvious from the deterministic problem alone — no AI call must
    be made to explain it."""
    import app.modules.website_analysis.service as website_service

    call_count = 0

    class _CountingFakeProvider(AIProvider):
        name = "fake"

        async def generate(self, request: AIRequest) -> AIResponse:
            nonlocal call_count
            call_count += 1
            output = SiteDiagnosticAIOutput(business_impact="should not be called")
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
        tenant = Tenant(id=tenant_id, name=f"Website Down Site Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Site Fora Do Ar",
                normalized_name="restaurante site fora do ar",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite-down.example",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()
            job = Job(
                tenant_id=tenant_id,
                type=JobType.WEBSITE_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        def _down_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        mock_transport = httpx.MockTransport(_down_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _CountingFakeProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        await handler._run(str(job_id), str(tenant_id), str(company_id))
        assert call_count == 0  # AI never called for a fully down site

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            website_result = await session.execute(
                select(Website).where(Website.company_id == company_id)
            )
            website = website_result.scalar_one()
            analysis_result = await session.execute(
                select(WebsiteAnalysis).where(WebsiteAnalysis.website_id == website.id)
            )
            analysis = analysis_result.scalar_one()
            assert analysis.digital_score is None
            assert len(analysis.findings["problems"]) == 1
            assert "HTTP 500" in analysis.findings["problems"][0]
            assert analysis.findings["ai_diagnostic"] is None
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_no_api_key_still_produces_deterministic_problems(app_session_factory, monkeypatch):
    """The deterministic score/problems must never depend on AI being
    configured — only the extra paragraph is skipped (see
    jobs/handlers/website_analysis.py's degrade-gracefully comment)."""
    import app.modules.website_analysis.service as website_service

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Website No Key Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Sem Chave IA",
                normalized_name="restaurante sem chave ia",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite-nokey.example",
                status=CompanyStatus.DISCOVERED,
            )
            session.add(company)
            await session.flush()
            job = Job(
                tenant_id=tenant_id,
                type=JobType.WEBSITE_ANALYSIS,
                status=JobStatus.PENDING,
                idempotency_key=str(company.id),
            )
            session.add(job)
            await session.commit()
            company_id, job_id = company.id, job.id

        mock_transport = httpx.MockTransport(_mock_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", None)

        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            website_result = await session.execute(
                select(Website).where(Website.company_id == company_id)
            )
            website = website_result.scalar_one()
            analysis_result = await session.execute(
                select(WebsiteAnalysis).where(WebsiteAnalysis.website_id == website.id)
            )
            analysis = analysis_result.scalar_one()
            assert analysis.digital_score is not None
            assert isinstance(analysis.findings["problems"], list)
            assert analysis.findings["ai_diagnostic"] is None

            updated_job = await session.get(Job, job_id)
            assert updated_job.status == JobStatus.COMPLETED
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

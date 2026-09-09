import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import set_tenant_context
from app.modules.ai_gateway.base import AIProvider, AIRequest, AIResponse
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.evidence.enums import EvidenceCategory, EvidencePolarity
from app.modules.evidence.models import Evidence
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job
from app.modules.website_analysis.ai_diagnostic import SiteDiagnosticAIOutput
from app.modules.website_analysis.crawler import WebsiteCrawler
from app.modules.website_analysis.enums import WebsiteStatus
from app.modules.website_analysis.models import Website, WebsiteAnalysis, WebsitePage

from .conftest import ADMIN_DATABASE_URL, requires_live_db


class _FakeQueue:
    """Same pattern as test_scheduler.py's own _FakeQueue --
    website_analysis.py chains into BUSINESS_ANALYSIS unconditionally after
    any successful analysis (even a down/blocked/JS-shell site still
    produces one); without this every test here enqueues a real job
    against the real shared Redis, referencing a throwaway test tenant
    that's about to be deleted (same class of leak found and fixed in
    test_business_analysis_job.py and test_scoring_job.py)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(self, *args) -> None:
        self.calls.append(args)


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
  <a href="mailto:contato@mocksite.example">Email</a>
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

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _FakeAIProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

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
            assert analysis.status == WebsiteStatus.GOOD
            assert analysis.opportunity_score is not None
            assert analysis.score_funcionamento == 100.0
            assert analysis.score_mobile == 100.0
            # Homepage loaded -> deterministic problems computed and the AI
            # diagnostic paragraph called (via the fake provider above).
            assert isinstance(analysis.findings["problems"], list)
            assert analysis.findings["ai_diagnostic"] == "Test business impact paragraph."

            evidence_result = await session.execute(
                select(Evidence).where(
                    Evidence.company_id == company_id, Evidence.claim == "Website status: GOOD"
                )
            )
            status_evidence = evidence_result.scalar_one()
            assert status_evidence.category == EvidenceCategory.WEBSITE_QUALITY
            assert status_evidence.polarity == EvidencePolarity.NEGATIVE

            updated_company = await session.get(Company, company_id)
            assert updated_company.email == "contato@mocksite.example"

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

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _FakeAIProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

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

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _CountingFakeProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

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
            # Fase 5 fix: a fully down site is OFFLINE with no quality score
            # at all — never a 0.0 "worst possible quality" reading (the
            # real bug this phase fixed, see scoring.py's compute_sub_scores).
            assert analysis.digital_score is None
            assert analysis.opportunity_score is None
            assert analysis.status == WebsiteStatus.OFFLINE
            assert len(analysis.findings["problems"]) == 1
            assert "HTTP 500" in analysis.findings["problems"][0]
            assert analysis.findings["ai_diagnostic"] is None

            evidence_result = await session.execute(
                select(Evidence).where(
                    Evidence.company_id == company_id, Evidence.claim == "Website status: OFFLINE"
                )
            )
            status_evidence = evidence_result.scalar_one()
            assert status_evidence.category == EvidenceCategory.WEBSITE_QUALITY
            # OFFLINE is a real, observed opportunity (no working site is
            # itself a gap) — never a negative judgment on a failure we
            # couldn't even confirm the cause of.
            assert status_evidence.polarity == EvidencePolarity.POSITIVE
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_anti_bot_blocked_site_is_never_scored_as_poor_quality(
    app_session_factory, monkeypatch
):
    """The Fase 5 absolute rule, end to end: a 403 (real-world anti-bot/WAF
    signal) must never be scored as a bad website, and must never trigger
    the paid AI diagnostic call — same cost-control gate as a fully down
    site."""
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
        tenant = Tenant(id=tenant_id, name=f"Website Blocked Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Bloqueado Por Anti-Bot",
                normalized_name="restaurante bloqueado por anti-bot",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite-blocked.example",
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

        def _blocked_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        mock_transport = httpx.MockTransport(_blocked_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _CountingFakeProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

        await handler._run(str(job_id), str(tenant_id), str(company_id))
        assert call_count == 0  # AI never called for a blocked site either

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
            assert analysis.status == WebsiteStatus.BLOCKED
            assert analysis.digital_score is None
            assert "bloqueio automático" in analysis.findings["problems"][0]

            evidence_result = await session.execute(
                select(Evidence).where(
                    Evidence.company_id == company_id, Evidence.claim == "Website status: BLOCKED"
                )
            )
            status_evidence = evidence_result.scalar_one()
            # The absolute rule at the evidence layer: BLOCKED is UNKNOWN
            # confidence/polarity, never a negative (or positive) claim.
            assert status_evidence.confidence.value == "UNKNOWN"
            assert status_evidence.polarity == status_evidence.polarity.UNKNOWN
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_js_only_shell_never_leaks_a_real_quality_score(app_session_factory, monkeypatch):
    """Regression test for a real bug this phase's own end-to-end
    validation caught: a JS-only SPA shell's near-empty HTML still parses to
    *some* low sub-scores (compute_sub_scores has no way to know the real
    content only exists after JS runs) — status.py correctly flags
    JS_REQUIRED, but without service.py's explicit nulling, digital_score
    would still carry that bogus low number (and the AI diagnostic would
    still be called with it), directly contradicting the status."""
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
        tenant = Tenant(id=tenant_id, name=f"Website JS Shell Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante SPA",
                normalized_name="restaurante spa",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite-spa.example",
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

        def _js_shell_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text='<html><body><div id="root"></div><script src="/bundle.js"></script></body></html>'
            )

        mock_transport = httpx.MockTransport(_js_shell_handler)
        monkeypatch.setattr(
            website_service,
            "WebsiteCrawler",
            lambda: WebsiteCrawler(transport=mock_transport),
        )

        import app.modules.jobs.handlers.website_analysis as handler

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _CountingFakeProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

        await handler._run(str(job_id), str(tenant_id), str(company_id))
        assert call_count == 0  # AI never called — no real score to explain

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
            assert analysis.status == WebsiteStatus.JS_REQUIRED
            # The actual bug: digital_score/opportunity_score must be None,
            # never a real-looking number computed from the unrendered shell.
            assert analysis.digital_score is None
            assert analysis.opportunity_score is None
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

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())
        from app.core.config import get_settings

        # No AnthropicProvider/get_provider_for_task mock here on purpose —
        # this test wants the real Model Router to hit the real "no key
        # configured" path (ProviderNotConfigured) and prove analyze_website
        # degrades gracefully, not a mocked shortcut around it.
        monkeypatch.setattr(get_settings(), "anthropic_api_key", None)

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


@requires_live_db
@pytest.mark.asyncio
async def test_crawl_never_overwrites_an_already_known_email(app_session_factory, monkeypatch):
    """Same non-destructive rule as companies/service.py's
    merge_missing_fields, just from a different source (the crawl itself)."""
    import app.modules.website_analysis.service as website_service

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Website Email Keep Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Email Conhecido",
                normalized_name="restaurante email conhecido",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                website="https://mocksite.example",
                email="ja-tinha@exemplo.com",
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

        monkeypatch.setattr(handler, "get_queue", lambda: _FakeQueue())

        import app.modules.ai_gateway.service as ai_gateway_service

        fake_router = lambda task: _FakeAIProvider()  # noqa: E731
        monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", fake_router)

        await handler._run(str(job_id), str(tenant_id), str(company_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            updated_company = await session.get(Company, company_id)
            # _mock_handler's homepage has a real mailto: link — proves this
            # is a deliberate no-overwrite, not just an empty crawl result.
            assert updated_company.email == "ja-tinha@exemplo.com"
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

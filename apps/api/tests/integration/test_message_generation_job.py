import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import set_tenant_context
from app.modules.ai_gateway.base import AIProvider, AIRequest, AIResponse
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job
from app.modules.messages.ai_writer import MessageAIOutput
from app.modules.messages.enums import MessageChannel, MessageStatus
from app.modules.messages.models import Message
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import ADMIN_DATABASE_URL, requires_live_db


class _FakeAIProvider(AIProvider):
    """Stands in for AnthropicProvider — automated tests must never spend
    real money (spec section 39)."""

    name = "fake"

    async def generate(self, request: AIRequest) -> AIResponse:
        output = MessageAIOutput(text="Oi! Notei que sua empresa nao tem site. Topa conversar?")
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


async def _seed_tenant_company_and_opportunity(admin_factory, app_session_factory, tenant_id, *, do_not_contact=False):
    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Message Gen Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

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
            status=CompanyStatus.DISCOVERED,
            do_not_contact=do_not_contact,
        )
        session.add(company)
        await session.flush()

        opportunity = Opportunity(
            tenant_id=tenant_id,
            company_id=company.id,
            type=OpportunityType.WEBSITE,
            status=OpportunityStatus.OPEN,
            reasons=["No website found."],
            problem="No website found.",
            potential_solution="Criar um site institucional.",
        )
        session.add(opportunity)
        await session.commit()
        return company.id, opportunity.id


@requires_live_db
@pytest.mark.asyncio
async def test_message_generation_job_creates_a_draft_message(app_session_factory, monkeypatch):
    import app.modules.jobs.handlers.message_generation as handler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    try:
        company_id, opportunity_id = await _seed_tenant_company_and_opportunity(
            admin_factory, app_session_factory, tenant_id
        )

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job = Job(
                tenant_id=tenant_id,
                type=JobType.MESSAGE_GENERATION,
                status=JobStatus.PENDING,
                idempotency_key=f"{opportunity_id}-WHATSAPP",
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _FakeAIProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        await handler._run(str(job_id), str(tenant_id), str(opportunity_id), "WHATSAPP")

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                select(Message).where(Message.opportunity_id == opportunity_id)
            )
            message = result.scalar_one()
            assert message.status == MessageStatus.DRAFT
            assert message.channel == MessageChannel.WHATSAPP
            assert "site" in message.generated_text

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
async def test_rerunning_generation_reuses_the_draft_not_a_new_ai_call(
    app_session_factory, monkeypatch
):
    """Cost control (spec section 39): a non-terminal message for the same
    (opportunity, channel) must not trigger a second AI call."""
    import app.modules.jobs.handlers.message_generation as handler

    call_count = 0

    class _CountingFakeProvider(AIProvider):
        name = "fake"

        async def generate(self, request: AIRequest) -> AIResponse:
            nonlocal call_count
            call_count += 1
            output = MessageAIOutput(text="Mensagem gerada.")
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

    try:
        company_id, opportunity_id = await _seed_tenant_company_and_opportunity(
            admin_factory, app_session_factory, tenant_id
        )

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _CountingFakeProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job1 = Job(
                tenant_id=tenant_id,
                type=JobType.MESSAGE_GENERATION,
                status=JobStatus.PENDING,
                idempotency_key=f"{opportunity_id}-EMAIL",
            )
            session.add(job1)
            await session.commit()
            job1_id = job1.id

        await handler._run(str(job1_id), str(tenant_id), str(opportunity_id), "EMAIL")
        assert call_count == 1

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job2 = Job(
                tenant_id=tenant_id,
                type=JobType.MESSAGE_GENERATION,
                status=JobStatus.PENDING,
                idempotency_key=f"{opportunity_id}-EMAIL-retry",
            )
            session.add(job2)
            await session.commit()
            job2_id = job2.id

        await handler._run(str(job2_id), str(tenant_id), str(opportunity_id), "EMAIL")
        assert call_count == 1  # still 1 — no second AI call
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_do_not_contact_blocks_message_generation(app_session_factory, monkeypatch):
    import app.modules.jobs.handlers.message_generation as handler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    try:
        company_id, opportunity_id = await _seed_tenant_company_and_opportunity(
            admin_factory, app_session_factory, tenant_id, do_not_contact=True
        )

        monkeypatch.setattr(handler, "AnthropicProvider", lambda api_key: _FakeAIProvider())
        monkeypatch.setattr(handler.get_settings(), "anthropic_api_key", "fake-key-for-test")

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            job = Job(
                tenant_id=tenant_id,
                type=JobType.MESSAGE_GENERATION,
                status=JobStatus.PENDING,
                idempotency_key=f"{opportunity_id}-WHATSAPP",
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        await handler._run(str(job_id), str(tenant_id), str(opportunity_id), "WHATSAPP")

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                select(Message).where(Message.opportunity_id == opportunity_id)
            )
            assert result.scalar_one_or_none() is None  # no message was created

            updated_job = await session.get(Job, job_id)
            assert updated_job.status == JobStatus.FAILED  # not retryable
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.messages.enums import MessageChannel, MessageStatus
from app.modules.messages.models import Message
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import requires_live_db


async def _seed_opportunity(session, tenant_id, suffix: str) -> Opportunity:
    company = Company(
        tenant_id=tenant_id,
        name=f"Messages RLS Test Co {suffix}",
        normalized_name=f"messages rls test co {suffix}",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        status=CompanyStatus.DISCOVERED,
    )
    session.add(company)
    await session.flush()
    opportunity = Opportunity(
        tenant_id=tenant_id,
        company_id=company.id,
        type=OpportunityType.WEBSITE,
        status=OpportunityStatus.OPEN,
        reasons=[],
    )
    session.add(opportunity)
    await session.flush()
    return opportunity


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_message(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        opportunity = await _seed_opportunity(session, tenant_a.id, "rls-read")
        message = Message(
            tenant_id=tenant_a.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.DRAFT,
            generated_text="Ola!",
        )
        session.add(message)
        await session.commit()
        message_id = message.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(Message, message_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(Message, message_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_message_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        opportunity = await _seed_opportunity(session, tenant_a.id, "rls-write-check")
        message = Message(
            tenant_id=tenant_b.id,
            opportunity_id=opportunity.id,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.DRAFT,
            generated_text="Ola!",
        )
        session.add(message)
        with pytest.raises(DBAPIError):
            await session.commit()

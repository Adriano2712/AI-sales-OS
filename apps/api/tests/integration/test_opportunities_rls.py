import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import requires_live_db


async def _seed_company(session, tenant_id, suffix: str) -> Company:
    company = Company(
        tenant_id=tenant_id,
        name=f"Opportunities RLS Test Co {suffix}",
        normalized_name=f"opportunities rls test co {suffix}",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        status=CompanyStatus.DISCOVERED,
    )
    session.add(company)
    await session.flush()
    return company


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_opportunity(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-read")
        opportunity = Opportunity(
            tenant_id=tenant_a.id,
            company_id=company.id,
            type=OpportunityType.WEBSITE,
            status=OpportunityStatus.OPEN,
            reasons=[],
        )
        session.add(opportunity)
        await session.commit()
        opportunity_id = opportunity.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(Opportunity, opportunity_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(Opportunity, opportunity_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_opportunity_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-write-check")
        opportunity = Opportunity(
            tenant_id=tenant_b.id,
            company_id=company.id,
            type=OpportunityType.WEBSITE,
            status=OpportunityStatus.OPEN,
            reasons=[],
        )
        session.add(opportunity)
        with pytest.raises(DBAPIError):
            await session.commit()

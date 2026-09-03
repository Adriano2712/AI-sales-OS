import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.website_analysis.models import Website

from .conftest import requires_live_db


async def _seed_company(session, tenant_id, suffix: str) -> Company:
    company = Company(
        tenant_id=tenant_id,
        name=f"Website RLS Test Co {suffix}",
        normalized_name=f"website rls test co {suffix}",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        website="https://example.com",
        status=CompanyStatus.DISCOVERED,
    )
    session.add(company)
    await session.flush()
    return company


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_website(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-read")
        website = Website(tenant_id=tenant_a.id, company_id=company.id, url=company.website)
        session.add(website)
        await session.commit()
        website_id = website.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(Website, website_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(Website, website_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_website_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-write-check")
        website = Website(tenant_id=tenant_b.id, company_id=company.id, url=company.website)
        session.add(website)
        with pytest.raises(DBAPIError):
            await session.commit()

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.companies.models import Company

from .conftest import requires_live_db


def _company(tenant_id, suffix: str) -> Company:
    return Company(
        tenant_id=tenant_id,
        name=f"Test Company {suffix}",
        normalized_name=f"test company {suffix}",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
    )


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_company(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = _company(tenant_a.id, "rls-read")
        session.add(company)
        await session.commit()
        company_id = company.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(Company, company_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(Company, company_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_company_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = _company(tenant_b.id, "rls-write-check")
        session.add(company)
        with pytest.raises(DBAPIError):
            await session.commit()

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company

from .conftest import requires_live_db


async def _seed_company(session, tenant_id, suffix: str) -> Company:
    company = Company(
        tenant_id=tenant_id,
        name=f"Business Analysis RLS Test Co {suffix}",
        normalized_name=f"business analysis rls test co {suffix}",
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
async def test_tenant_cannot_read_another_tenants_business_analysis(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-read")
        analysis = BusinessAnalysis(
            tenant_id=tenant_a.id,
            company_id=company.id,
            overall_score=50.0,
            findings=[],
            problems=[],
            analyzed_at=datetime.now(UTC),
        )
        session.add(analysis)
        await session.commit()
        analysis_id = analysis.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(BusinessAnalysis, analysis_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(BusinessAnalysis, analysis_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_business_analysis_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-write-check")
        analysis = BusinessAnalysis(
            tenant_id=tenant_b.id,
            company_id=company.id,
            findings=[],
            problems=[],
            analyzed_at=datetime.now(UTC),
        )
        session.add(analysis)
        with pytest.raises(DBAPIError):
            await session.commit()

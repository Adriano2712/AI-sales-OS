from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.evidence.enums import EvidenceConfidence
from app.modules.evidence.models import Evidence

from .conftest import requires_live_db


async def _seed_company(session, tenant_id, suffix: str) -> Company:
    # evidence.company_id has a real FK to companies.id — a fake/random UUID
    # would just violate that constraint rather than exercising RLS at all.
    company = Company(
        tenant_id=tenant_id,
        name=f"Evidence RLS Test Co {suffix}",
        normalized_name=f"evidence rls test co {suffix}",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        status=CompanyStatus.DISCOVERED,
    )
    session.add(company)
    await session.flush()
    return company


def _evidence(tenant_id, company_id, suffix: str) -> Evidence:
    return Evidence(
        tenant_id=tenant_id,
        company_id=company_id,
        claim=f"test claim {suffix}",
        source="test",
        collected_at=datetime.now(UTC),
        confidence=EvidenceConfidence.HIGH,
    )


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_evidence(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = await _seed_company(session, tenant_a.id, "rls-read")
        evidence = _evidence(tenant_a.id, company.id, "rls-read")
        session.add(evidence)
        await session.commit()
        evidence_id = evidence.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        assert await session.get(Evidence, evidence_id) is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await session.get(Evidence, evidence_id) is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_evidence_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        # The company belongs to tenant_a (so the FK itself is satisfiable);
        # what's under test is evidence.tenant_id being stamped as tenant_b.
        company = await _seed_company(session, tenant_a.id, "rls-write-check")
        evidence = _evidence(tenant_b.id, company.id, "rls-write-check")
        session.add(evidence)
        with pytest.raises(DBAPIError):
            await session.commit()

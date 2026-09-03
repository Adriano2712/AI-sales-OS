import httpx
import pytest

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import requires_live_db, requires_matching_env


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_min_confidence_filter_excludes_low_confidence_opportunities(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Confidence Filter Test Co",
            normalized_name="confidence filter test co",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.flush()

        high_confidence = Opportunity(
            tenant_id=tenant_a.id,
            company_id=company.id,
            type=OpportunityType.WEBSITE,
            status=OpportunityStatus.OPEN,
            reasons=[],
            opportunity_score=80.0,
            confidence=90.0,
        )
        low_confidence = Opportunity(
            tenant_id=tenant_a.id,
            company_id=company.id,
            type=OpportunityType.OTHER,
            status=OpportunityStatus.OPEN,
            reasons=[],
            opportunity_score=80.0,
            confidence=20.0,
        )
        session.add_all([high_confidence, low_confidence])
        await session.commit()
        high_id, low_id = high_confidence.id, low_confidence.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/opportunities", params={"min_confidence": 50}, headers=headers
        )
        assert response.status_code == 200
        ids = {o["id"] for o in response.json()}
        assert str(high_id) in ids
        assert str(low_id) not in ids

        unfiltered = await client.get("/api/v1/opportunities", headers=headers)
        unfiltered_ids = {o["id"] for o in unfiltered.json()}
        assert str(high_id) in unfiltered_ids
        assert str(low_id) in unfiltered_ids


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_list_response_includes_next_action_and_potential_solution(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Next Action Test Co",
            normalized_name="next action test co",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.flush()

        opportunity = Opportunity(
            tenant_id=tenant_a.id,
            company_id=company.id,
            type=OpportunityType.WEBSITE,
            status=OpportunityStatus.OPEN,
            reasons=[],
            potential_solution="Criar um site institucional/comercial.",
        )
        session.add(opportunity)
        await session.commit()
        opportunity_id = opportunity.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/opportunities", headers=headers)
        assert response.status_code == 200
        [row] = [o for o in response.json() if o["id"] == str(opportunity_id)]
        assert row["next_action"] == "Revisar oportunidade"  # status=OPEN
        assert row["potential_solution"] == "Criar um site institucional/comercial."

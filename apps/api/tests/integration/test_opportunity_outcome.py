import httpx
import pytest

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.opportunities.enums import OpportunityStatus, OpportunityType
from app.modules.opportunities.models import Opportunity

from .conftest import requires_live_db, requires_matching_env


async def _seed_company_and_opportunity(app_session_factory, tenant_id):
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        company = Company(
            tenant_id=tenant_id,
            name="Outcome Test Co",
            normalized_name="outcome test co",
            segment="clinics",
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
            opportunity_score=70.0,
        )
        session.add(opportunity)
        await session.commit()
        return opportunity.id


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_outcome_is_null_by_default_never_a_fabricated_stage(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}
    opportunity_id = await _seed_company_and_opportunity(app_session_factory, tenant_a.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/opportunities/{opportunity_id}", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] is None
        assert body["outcome_notes"] is None


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_patch_outcome_does_not_touch_status(
    authenticated_client, app_session_factory, two_tenants
):
    """outcome/outcome_notes are independent of status — a human logging
    real-world sales progress must not accidentally move OPEN -> something
    else (spec: two separate axes, see opportunities/schemas.py)."""
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}
    opportunity_id = await _seed_company_and_opportunity(app_session_factory, tenant_a.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/opportunities/{opportunity_id}",
            json={"outcome": "PROPOSAL_SENT", "outcome_notes": "Proposta de R$3.000 enviada."},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "PROPOSAL_SENT"
        assert body["outcome_notes"] == "Proposta de R$3.000 enviada."
        assert body["status"] == "OPEN"  # untouched


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_outcome_can_be_corrected_freely_no_transition_enforcement(
    authenticated_client, app_session_factory, two_tenants
):
    """Real-world state, not a system-driven workflow — any value must be
    reachable from any other (e.g. undoing a mistaken WON)."""
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}
    opportunity_id = await _seed_company_and_opportunity(app_session_factory, tenant_a.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.patch(
            f"/api/v1/opportunities/{opportunity_id}", json={"outcome": "WON"}, headers=headers
        )
        assert first.status_code == 200
        assert first.json()["outcome"] == "WON"

        corrected = await client.patch(
            f"/api/v1/opportunities/{opportunity_id}",
            json={"outcome": "CONTACTED"},
            headers=headers,
        )
        assert corrected.status_code == 200
        assert corrected.json()["outcome"] == "CONTACTED"

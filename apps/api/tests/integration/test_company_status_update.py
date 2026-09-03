import httpx
import pytest

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company

from .conftest import requires_live_db, requires_matching_env


def _company(tenant_id, status: CompanyStatus) -> Company:
    return Company(
        tenant_id=tenant_id,
        name="Restaurante Fechado",
        normalized_name="restaurante fechado",
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        status=status,
    )


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_marking_a_company_invalid_removes_it_from_the_default_list(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = _company(tenant_a.id, CompanyStatus.DISCOVERED)
        session.add(company)
        await session.commit()
        company_id = company.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/api/v1/companies", headers=headers)
        assert any(c["id"] == str(company_id) for c in before.json())

        patched = await client.patch(
            f"/api/v1/companies/{company_id}", json={"status": "INVALID"}, headers=headers
        )
        assert patched.status_code == 200
        assert patched.json()["status"] == "INVALID"

        after = await client.get("/api/v1/companies", headers=headers)
        assert not any(c["id"] == str(company_id) for c in after.json())

        # Still reachable when explicitly asked for.
        explicit = await client.get(
            "/api/v1/companies", params={"status": "INVALID"}, headers=headers
        )
        assert any(c["id"] == str(company_id) for c in explicit.json())

        # And always reachable by id, regardless of status.
        detail = await client.get(f"/api/v1/companies/{company_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["status"] == "INVALID"


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_viewer_role_cannot_update_company_status(authenticated_client, two_tenants):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.VIEWER)
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import uuid

        response = await client.patch(
            f"/api/v1/companies/{uuid.uuid4()}", json={"status": "INVALID"}, headers=headers
        )
        assert response.status_code == 403

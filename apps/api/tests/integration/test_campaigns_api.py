import httpx
import pytest

from .conftest import requires_live_db, requires_matching_env


def _campaign_payload(**overrides) -> dict:
    payload = {
        "name": "Restaurantes Sorocaba",
        "segment": "restaurants",
        "cities": ["Sorocaba", "Votorantim"],
        "state": "SP",
        "country": "BR",
        "target_quantity": 33,
        "filters": {},
    }
    payload.update(overrides)
    return payload


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_full_campaign_lifecycle(authenticated_client, two_tenants):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns", json=_campaign_payload(), headers=headers
        )
        assert created.status_code == 201, created.text
        campaign = created.json()
        assert campaign["status"] == "DRAFT"
        campaign_id = campaign["id"]

        listed = await client.get("/api/v1/campaigns", headers=headers)
        assert listed.status_code == 200
        assert any(c["id"] == campaign_id for c in listed.json())

        fetched = await client.get(f"/api/v1/campaigns/{campaign_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Restaurantes Sorocaba"

        # Can't start a run before the campaign is ACTIVE.
        premature_run = await client.post(
            f"/api/v1/campaigns/{campaign_id}/runs", headers=headers
        )
        assert premature_run.status_code == 409

        # DRAFT -> PAUSED is not a valid transition.
        invalid_transition = await client.patch(
            f"/api/v1/campaigns/{campaign_id}", json={"status": "PAUSED"}, headers=headers
        )
        assert invalid_transition.status_code == 409

        activated = await client.patch(
            f"/api/v1/campaigns/{campaign_id}", json={"status": "ACTIVE"}, headers=headers
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "ACTIVE"

        run_created = await client.post(
            f"/api/v1/campaigns/{campaign_id}/runs", headers=headers
        )
        assert run_created.status_code == 201, run_created.text
        run = run_created.json()
        assert run["status"] == "PENDING"
        assert run["campaign_id"] == campaign_id

        runs_listed = await client.get(
            f"/api/v1/campaigns/{campaign_id}/runs", headers=headers
        )
        assert runs_listed.status_code == 200
        assert len(runs_listed.json()) == 1

        run_fetched = await client.get(
            f"/api/v1/campaigns/{campaign_id}/runs/{run['id']}", headers=headers
        )
        assert run_fetched.status_code == 200


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_viewer_role_cannot_create_campaign(authenticated_client, two_tenants):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.VIEWER)
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns", json=_campaign_payload(), headers=headers
        )
        assert response.status_code == 403

        # But VIEWER can still read.
        listed = await client.get("/api/v1/campaigns", headers=headers)
        assert listed.status_code == 200


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_tenant_cannot_see_another_tenants_campaign_via_api(
    authenticated_client, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, tenant_b = two_tenants
    token_a = await authenticated_client(tenant_a.id, Role.ADMIN)
    token_b = await authenticated_client(tenant_b.id, Role.ADMIN)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            json=_campaign_payload(),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        campaign_id = created.json()["id"]

        cross_tenant = await client.get(
            f"/api/v1/campaigns/{campaign_id}", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert cross_tenant.status_code == 404

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
        "services": ["website", "e-commerce"],
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
        # Fase 6 ICP field — the services this campaign is selling, the
        # anchor for SERVICE_FIT_SCORE.
        assert campaign["services"] == ["website", "e-commerce"]
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


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_autonomous_discovery_rejects_target_quantity_over_the_safety_cap(
    authenticated_client, two_tenants
):
    """Fase 9: the master spec's own escalation discipline (start small,
    never a large unattended batch) enforced at creation time — a campaign
    can't opt into daily autonomous runs with a large target_quantity."""
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/campaigns",
            json=_campaign_payload(auto_discovery_enabled=True, target_quantity=11),
            headers=headers,
        )
        assert response.status_code == 409, response.text

        # A manual (non-autonomous) campaign is unaffected by the cap.
        manual = await client.post(
            "/api/v1/campaigns",
            json=_campaign_payload(auto_discovery_enabled=False, target_quantity=33),
            headers=headers,
        )
        assert manual.status_code == 201, manual.text


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_autonomous_discovery_allows_target_quantity_at_the_safety_cap(
    authenticated_client, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, _ = two_tenants
    token = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/campaigns",
            json=_campaign_payload(auto_discovery_enabled=True, target_quantity=10),
            headers=headers,
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]
        assert created.json()["auto_discovery_enabled"] is True

        # PATCHing target_quantity up past the cap while still autonomous
        # must also be rejected — the check applies to the resolved final
        # state, not just at creation time.
        patched = await client.patch(
            f"/api/v1/campaigns/{campaign_id}",
            json={"target_quantity": 15},
            headers=headers,
        )
        assert patched.status_code == 409, patched.text

        # But turning autonomy off first, then raising the quantity, works.
        disabled = await client.patch(
            f"/api/v1/campaigns/{campaign_id}",
            json={"auto_discovery_enabled": False},
            headers=headers,
        )
        assert disabled.status_code == 200
        raised = await client.patch(
            f"/api/v1/campaigns/{campaign_id}",
            json={"target_quantity": 15},
            headers=headers,
        )
        assert raised.status_code == 200

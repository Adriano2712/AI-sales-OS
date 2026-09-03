import pytest
from sqlalchemy.exc import DBAPIError

from app.core.db import set_tenant_context
from app.modules.campaigns.enums import CampaignStatus
from app.modules.campaigns.models import Campaign

from .conftest import requires_live_db


def _campaign(tenant_id, idempotency_suffix: str) -> Campaign:
    return Campaign(
        tenant_id=tenant_id,
        name=f"Test Campaign {idempotency_suffix}",
        segment="restaurants",
        cities=["Sorocaba"],
        state="SP",
        country="BR",
        target_quantity=33,
        status=CampaignStatus.DRAFT,
    )


@requires_live_db
@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_campaign(app_session_factory, two_tenants):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        campaign = _campaign(tenant_a.id, "rls-read")
        session.add(campaign)
        await session.commit()
        campaign_id = campaign.id

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_b.id)
        fetched = await session.get(Campaign, campaign_id)
        assert fetched is None

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        fetched = await session.get(Campaign, campaign_id)
        assert fetched is not None


@requires_live_db
@pytest.mark.asyncio
async def test_cannot_insert_campaign_stamped_with_a_different_tenant(
    app_session_factory, two_tenants
):
    tenant_a, tenant_b = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        campaign = _campaign(tenant_b.id, "rls-write-check")
        session.add(campaign)
        with pytest.raises(DBAPIError):
            await session.commit()

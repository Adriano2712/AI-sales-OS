from datetime import UTC, datetime

import httpx
import pytest

from app.core.db import set_tenant_context
from app.modules.ai_gateway.models import AICall
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.opportunities.enums import (
    OpportunityClassification,
    OpportunityOutcome,
    OpportunityStatus,
    OpportunityType,
)
from app.modules.opportunities.models import Opportunity
from app.modules.website_analysis.enums import WebsiteStatus
from app.modules.website_analysis.models import Website, WebsiteAnalysis

from .conftest import requires_live_db, requires_matching_env


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_dashboard_summary_aggregates_only_the_caller_tenants_data(
    authenticated_client, app_session_factory, two_tenants
):
    from app.main import app
    from app.modules.tenancy.enums import Role

    tenant_a, tenant_b = two_tenants
    token_a = await authenticated_client(tenant_a.id, Role.ADMIN)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)

        campaign = Campaign(
            tenant_id=tenant_a.id,
            name="Dashboard Test Campaign",
            segment="restaurants",
            cities=["Sorocaba"],
            state="SP",
            country="BR",
            target_quantity=10,
            status=CampaignStatus.ACTIVE,
        )
        session.add(campaign)
        await session.flush()

        run = CampaignRun(
            tenant_id=tenant_a.id,
            campaign_id=campaign.id,
            status=CampaignRunStatus.COMPLETED,
            companies_found=10,
            companies_validated=8,
            duplicates=2,
            enriched=8,
            analyzed=8,
        )
        session.add(run)

        company = Company(
            tenant_id=tenant_a.id,
            name="Dashboard Test Co",
            normalized_name="dashboard test co",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            status=CompanyStatus.DISCOVERED,
        )
        # Fase 12 (Analytics): a website-found company (enrichment success)...
        company_with_website = Company(
            tenant_id=tenant_a.id,
            name="Dashboard Test Co With Website",
            normalized_name="dashboard test co with website",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            website="https://example.com",
            status=CompanyStatus.VALIDATED,
        )
        # ...and an INVALID one (neither website-found, since it also has none).
        invalid_company = Company(
            tenant_id=tenant_a.id,
            name="Dashboard Test Co Invalid",
            normalized_name="dashboard test co invalid",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            status=CompanyStatus.INVALID,
        )
        session.add_all([company, company_with_website, invalid_company])
        await session.flush()

        website = Website(
            tenant_id=tenant_a.id, company_id=company_with_website.id, url="https://example.com"
        )
        session.add(website)
        await session.flush()

        session.add(
            WebsiteAnalysis(
                tenant_id=tenant_a.id,
                website_id=website.id,
                digital_score=80.0,
                status=WebsiteStatus.GOOD,
                analyzed_at=datetime.now(UTC),
            )
        )
        session.add(
            BusinessAnalysis(
                tenant_id=tenant_a.id,
                company_id=company.id,
                business_fit_score=70.0,
                analyzed_at=datetime.now(UTC),
            )
        )

        session.add_all(
            [
                Opportunity(
                    tenant_id=tenant_a.id,
                    company_id=company.id,
                    type=OpportunityType.WEBSITE,
                    status=OpportunityStatus.OPEN,
                    reasons=[],
                    opportunity_score=95.0,
                    classification=OpportunityClassification.HIGH,
                ),
                Opportunity(
                    tenant_id=tenant_a.id,
                    company_id=company.id,
                    type=OpportunityType.OTHER,
                    status=OpportunityStatus.OPEN,
                    reasons=[],
                    opportunity_score=65.0,
                    classification=OpportunityClassification.REVIEW,
                    outcome=OpportunityOutcome.WON,
                ),
                Opportunity(
                    tenant_id=tenant_a.id,
                    company_id=company.id,
                    type=OpportunityType.AUTOMATION,
                    status=OpportunityStatus.OPEN,
                    reasons=[],
                    opportunity_score=40.0,
                    outcome=OpportunityOutcome.CONTACTED,
                ),
                # Fase 12: exercises funnel.approved, distinct from outcome.
                Opportunity(
                    tenant_id=tenant_a.id,
                    company_id=company_with_website.id,
                    type=OpportunityType.WEBSITE,
                    status=OpportunityStatus.APPROVED,
                    reasons=[],
                    opportunity_score=55.0,
                ),
            ]
        )

        session.add(
            AICall(
                tenant_id=tenant_a.id,
                task="business_analysis",
                provider="anthropic",
                model="claude-sonnet-5",
                estimated_cost_usd=0.012,
                status="success",
            )
        )
        await session.commit()

    # Tenant B has none of this data — proves the aggregation is tenant-scoped,
    # not a global sum (same isolation guarantee RLS gives every other table).
    token_b = await authenticated_client(tenant_b.id, Role.ADMIN)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response_a = await client.get("/api/v1/dashboard/summary", headers=headers_a)
        assert response_a.status_code == 200
        summary_a = response_a.json()
        assert summary_a["discovery"]["companies_found"] == 10
        assert summary_a["discovery"]["companies_validated"] == 8
        assert summary_a["discovery"]["invalid"] == 1
        assert summary_a["opportunities"]["total"] == 4
        assert summary_a["opportunities"]["high"] == 1
        assert summary_a["opportunities"]["review"] == 1
        assert summary_a["funnel"]["approved"] == 1
        assert summary_a["funnel"]["won"] == 1
        assert summary_a["funnel"]["contacted"] == 1
        assert summary_a["funnel"]["replied"] == 0
        assert summary_a["funnel"]["meetings"] is None
        # 2 non-duplicate companies without a website (the DISCOVERED one +
        # the INVALID one) vs 1 with (the VALIDATED one).
        assert summary_a["enrichment"]["website_found"] == 1
        assert summary_a["enrichment"]["website_not_found"] == 2
        assert summary_a["enrichment"]["success_rate"] == pytest.approx(33.3)
        assert summary_a["analysis"]["companies_analyzed"] == 1
        assert summary_a["analysis"]["average_digital_score"] == pytest.approx(80.0)
        assert summary_a["analysis"]["average_business_fit"] == pytest.approx(70.0)
        assert summary_a["cost"]["ai_calls"] == 1
        assert summary_a["cost"]["total_estimated_cost_usd"] == 0.012
        # CampaignRun.companies_found=10, .analyzed=8, total_opportunities=4.
        assert summary_a["cost"]["cost_per_company"] == pytest.approx(0.0012)
        assert summary_a["cost"]["cost_per_analysis"] == pytest.approx(0.0015)
        assert summary_a["cost"]["cost_per_opportunity"] == pytest.approx(0.003)

        response_b = await client.get("/api/v1/dashboard/summary", headers=headers_b)
        assert response_b.status_code == 200
        summary_b = response_b.json()
        assert summary_b["discovery"]["companies_found"] == 0
        assert summary_b["discovery"]["invalid"] == 0
        assert summary_b["opportunities"]["total"] == 0
        assert summary_b["funnel"]["approved"] == 0
        assert summary_b["funnel"]["won"] == 0
        assert summary_b["funnel"]["meetings"] is None
        assert summary_b["enrichment"]["website_found"] == 0
        assert summary_b["enrichment"]["success_rate"] is None
        assert summary_b["analysis"]["companies_analyzed"] == 0
        assert summary_b["analysis"]["average_digital_score"] is None
        assert summary_b["cost"]["ai_calls"] == 0
        assert summary_b["cost"]["cost_per_company"] is None
        assert summary_b["cost"]["cost_per_analysis"] is None
        assert summary_b["cost"]["cost_per_opportunity"] is None

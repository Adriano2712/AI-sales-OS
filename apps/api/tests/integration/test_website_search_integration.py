import pytest
from sqlalchemy import select

# Registers CampaignRun etc. with SQLAlchemy so Company.campaign_run_id's FK
# string resolves (see model_registry's own docstring for the Fase 2 bug
# this fixes) -- this file never uses CampaignRun directly, unlike sibling
# integration tests that happen to import it themselves.
from app.core import model_registry  # noqa: F401
from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company, CompanySource
from app.modules.enrichment import website_search
from app.modules.enrichment.website_search import find_website_via_search
from app.modules.evidence.enums import EvidenceConfidence, EvidencePolarity
from app.modules.evidence.models import Evidence

from .conftest import requires_live_db


@requires_live_db
@pytest.mark.asyncio
async def test_find_website_via_search_fills_gap_when_a_plausible_match_is_found(
    app_session_factory, two_tenants, monkeypatch
):
    """Real case (Fase 13): a company Overpass/Apify returned with no
    website — the exact gap found on a real Chicago campaign ("La Cocina de
    Irma" had no `website` field anywhere in its Google Maps listing, but a
    real web search for it does find one)."""
    tenant_a, _ = two_tenants

    async def fake_search(company_name, city, state):
        return (
            "https://lacocinadeirma.com",
            "La Cocina de Irma - Authentic Mexican Restaurant",
            "Family owned since 1998 in Chicago.",
        )

    monkeypatch.setattr(website_search, "search_company_website", fake_search)

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="La Cocina de Irma",
            normalized_name="la cocina de irma",
            segment="restaurants",
            city="Chicago",
            state="IL",
            country="US",
            website=None,
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        found = await find_website_via_search(session, tenant_a.id, company)
        await session.commit()

        assert found is True
        assert company.website == "https://lacocinadeirma.com"

        await set_tenant_context(session, tenant_a.id)
        source_result = await session.execute(
            select(CompanySource).where(CompanySource.company_id == company.id)
        )
        source = source_result.scalar_one()
        assert source.provider == "brave_search"
        assert source.external_id == "https://lacocinadeirma.com"

        evidence_result = await session.execute(
            select(Evidence).where(Evidence.company_id == company.id)
        )
        evidence = evidence_result.scalar_one()
        assert evidence.claim == "website (via busca web): https://lacocinadeirma.com"
        # MEDIUM, not HIGH -- a search match is inferred, not a value the
        # business's own Google/OSM listing directly reported (see
        # enrich_company's HIGH-confidence core-field evidence for contrast).
        assert evidence.confidence == EvidenceConfidence.MEDIUM
        assert evidence.polarity == EvidencePolarity.POSITIVE


@requires_live_db
@pytest.mark.asyncio
async def test_find_website_via_search_leaves_company_unchanged_when_nothing_plausible(
    app_session_factory, two_tenants, monkeypatch
):
    async def fake_search(company_name, city, state):
        return None

    monkeypatch.setattr(website_search, "search_company_website", fake_search)

    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Empresa Sem Site Nenhum",
            normalized_name="empresa sem site nenhum",
            segment="restaurants",
            city="Chicago",
            state="IL",
            country="US",
            website=None,
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        found = await find_website_via_search(session, tenant_a.id, company)
        await session.commit()

        assert found is False
        assert company.website is None

        await set_tenant_context(session, tenant_a.id)
        source_result = await session.execute(
            select(CompanySource).where(CompanySource.company_id == company.id)
        )
        assert source_result.first() is None

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company, CompanySource
from app.modules.enrichment.service import enrich_company
from app.modules.evidence.enums import EvidenceConfidence
from app.modules.evidence.models import Evidence

from .conftest import requires_live_db


@requires_live_db
@pytest.mark.asyncio
async def test_enrich_company_records_unknown_evidence_for_missing_core_fields(
    app_session_factory, two_tenants
):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Restaurante Sem Contato",
            normalized_name="restaurante sem contato",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            phone=None,
            website=None,
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.flush()

        source = CompanySource(
            tenant_id=tenant_a.id,
            company_id=company.id,
            provider="overpass",
            external_id="node/999",
            collected_at=datetime.now(UTC),
            data={"osm_tags": {"name": "Restaurante Sem Contato", "amenity": "restaurant"}},
        )
        session.add(source)
        await session.commit()

        # SET LOCAL is transaction-scoped — the commit above ended the
        # transaction it was set in, so it must be set again for the
        # transaction enrich_company's inserts run in.
        await set_tenant_context(session, tenant_a.id)
        await enrich_company(session, tenant_a.id, company)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        result = await session.execute(
            select(Evidence).where(Evidence.company_id == company.id)
        )
        evidence_by_claim = {e.claim: e for e in result.scalars()}

        assert "No public evidence of a phone was found" in evidence_by_claim
        assert (
            evidence_by_claim["No public evidence of a phone was found"].confidence
            == EvidenceConfidence.UNKNOWN
        )
        assert "No public evidence of a website was found" in evidence_by_claim


@requires_live_db
@pytest.mark.asyncio
async def test_enrich_company_records_high_confidence_evidence_for_present_fields(
    app_session_factory, two_tenants
):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Restaurante Completo",
            normalized_name="restaurante completo",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            phone="1533334444",
            website="https://restaurantecompleto.com.br",
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.flush()

        source = CompanySource(
            tenant_id=tenant_a.id,
            company_id=company.id,
            provider="overpass",
            external_id="node/1000",
            collected_at=datetime.now(UTC),
            data={
                "osm_tags": {
                    "name": "Restaurante Completo",
                    "opening_hours": "Mo-Su 11:00-23:00",
                    "cuisine": "pizza",
                }
            },
        )
        session.add(source)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        await enrich_company(session, tenant_a.id, company)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        result = await session.execute(
            select(Evidence).where(Evidence.company_id == company.id)
        )
        evidence_by_claim = {e.claim: e for e in result.scalars()}

        assert evidence_by_claim["phone: 1533334444"].confidence == EvidenceConfidence.HIGH
        assert (
            evidence_by_claim["website: https://restaurantecompleto.com.br"].confidence
            == EvidenceConfidence.HIGH
        )
        assert "opening_hours: Mo-Su 11:00-23:00" in evidence_by_claim
        assert "cuisine: pizza" in evidence_by_claim


@requires_live_db
@pytest.mark.asyncio
async def test_enrich_company_is_idempotent(app_session_factory, two_tenants):
    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        company = Company(
            tenant_id=tenant_a.id,
            name="Restaurante Idempotente",
            normalized_name="restaurante idempotente",
            segment="restaurants",
            city="Sorocaba",
            state="SP",
            country="BR",
            status=CompanyStatus.DISCOVERED,
        )
        session.add(company)
        await session.flush()
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        await enrich_company(session, tenant_a.id, company)
        await session.commit()
        await set_tenant_context(session, tenant_a.id)
        await enrich_company(session, tenant_a.id, company)
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        result = await session.execute(
            select(Evidence).where(Evidence.company_id == company.id)
        )
        evidence = result.scalars().all()
        # Two core-field checks (phone, website), run twice — must not double up.
        assert len(evidence) == 2

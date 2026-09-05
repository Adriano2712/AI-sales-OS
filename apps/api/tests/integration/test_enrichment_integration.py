from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.db import set_tenant_context
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company, CompanySource
from app.modules.enrichment.service import enrich_company
from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
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
        phone_evidence = evidence_by_claim["No public evidence of a phone was found"]
        assert phone_evidence.confidence == EvidenceConfidence.UNKNOWN
        # Opportunity Signal absolute rule (Fase 3): absence is UNKNOWN, never
        # a negative signal just because we didn't find a phone number.
        assert phone_evidence.polarity == EvidencePolarity.UNKNOWN
        assert "No public evidence of a website was found" in evidence_by_claim

        # Fase 4: instagram and Google review data get the exact same
        # UNKNOWN-not-NEGATIVE treatment when absent.
        assert "No public evidence of a instagram was found" in evidence_by_claim
        instagram_evidence = evidence_by_claim["No public evidence of a instagram was found"]
        assert instagram_evidence.confidence == EvidenceConfidence.UNKNOWN
        assert instagram_evidence.polarity == EvidencePolarity.UNKNOWN
        assert instagram_evidence.category == EvidenceCategory.SOCIAL_PRESENCE

        assert "No Google rating/review data was found" in evidence_by_claim
        reviews_evidence = evidence_by_claim["No Google rating/review data was found"]
        assert reviews_evidence.confidence == EvidenceConfidence.UNKNOWN
        assert reviews_evidence.polarity == EvidencePolarity.UNKNOWN
        assert reviews_evidence.category == EvidenceCategory.CUSTOMER_VALIDATION


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
            instagram_url="https://instagram.com/restaurantecompleto",
            google_rating=4.8,
            google_review_count=512,
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

        phone_evidence = evidence_by_claim["phone: 1533334444"]
        assert phone_evidence.confidence == EvidenceConfidence.HIGH
        # Real contact info found — a positive contactability signal (Fase 3).
        assert phone_evidence.polarity == EvidencePolarity.POSITIVE
        assert phone_evidence.category == EvidenceCategory.CONTACTABILITY

        website_evidence = evidence_by_claim["website: https://restaurantecompleto.com.br"]
        assert website_evidence.confidence == EvidenceConfidence.HIGH
        assert website_evidence.polarity == EvidencePolarity.POSITIVE

        assert "opening_hours: Mo-Su 11:00-23:00" in evidence_by_claim
        opening_hours_evidence = evidence_by_claim["opening_hours: Mo-Su 11:00-23:00"]
        assert opening_hours_evidence.polarity == EvidencePolarity.NEUTRAL
        assert opening_hours_evidence.category == EvidenceCategory.BUSINESS_STATUS

        assert "cuisine: pizza" in evidence_by_claim
        assert evidence_by_claim["cuisine: pizza"].category == EvidenceCategory.OTHER

        # Fase 4: instagram is a core field now — presence is POSITIVE/
        # SOCIAL_PRESENCE, matching the spec's "presença social ativa"
        # positive example.
        instagram_evidence = evidence_by_claim["instagram: https://instagram.com/restaurantecompleto"]
        assert instagram_evidence.confidence == EvidenceConfidence.HIGH
        assert instagram_evidence.polarity == EvidencePolarity.POSITIVE
        assert instagram_evidence.category == EvidenceCategory.SOCIAL_PRESENCE

        # Fase 4: real Google review data is CUSTOMER_VALIDATION — proof of
        # an active, discoverable business (spec's "muitas avaliações,
        # rating alto" positive example), never a judgment on the rating's
        # actual value.
        reviews_evidence = evidence_by_claim["Google rating: 4.8 (512 reviews)"]
        assert reviews_evidence.confidence == EvidenceConfidence.HIGH
        assert reviews_evidence.polarity == EvidencePolarity.POSITIVE
        assert reviews_evidence.category == EvidenceCategory.CUSTOMER_VALIDATION


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
        # Four core-field checks (phone, website, instagram, google reviews),
        # run twice — must not double up.
        assert len(evidence) == 4

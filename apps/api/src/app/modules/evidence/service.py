import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
from app.modules.evidence.models import Evidence


class InvalidEvidencePolarity(ValueError):
    """Raised when a caller tries to pair EvidenceConfidence.UNKNOWN with
    anything other than EvidencePolarity.UNKNOWN — the one absolute rule of
    the Opportunity Signal concept (Fase 3): absence of evidence is never
    recorded as a positive or negative signal, only as unknown."""


async def get_or_create_evidence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    claim: str,
    source: str,
    confidence: EvidenceConfidence,
    polarity: EvidencePolarity,
    category: EvidenceCategory,
    source_url: str | None = None,
    supporting_data: dict | None = None,
) -> Evidence:
    """Idempotent by (tenant, company, claim): re-running enrichment for the
    same company shouldn't pile up duplicate identical claims (spec section
    54's idempotency principle, extended to evidence).

    Enforces the Opportunity Signal's one absolute rule in code, not just by
    convention: UNKNOWN confidence ("no evidence was found") can never be
    recorded as a POSITIVE or NEGATIVE signal — only ever UNKNOWN."""
    if confidence == EvidenceConfidence.UNKNOWN and polarity != EvidencePolarity.UNKNOWN:
        raise InvalidEvidencePolarity(
            f"claim {claim!r} has confidence=UNKNOWN but polarity={polarity.value} — "
            "absence of evidence must be recorded as polarity=UNKNOWN, never a signal"
        )

    existing = await db.execute(
        select(Evidence).where(
            Evidence.tenant_id == tenant_id,
            Evidence.company_id == company_id,
            Evidence.claim == claim,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    evidence = Evidence(
        tenant_id=tenant_id,
        company_id=company_id,
        claim=claim,
        source=source,
        source_url=source_url,
        collected_at=datetime.now(UTC),
        confidence=confidence,
        polarity=polarity,
        category=category,
        supporting_data=supporting_data or {},
    )
    db.add(evidence)
    await db.flush()
    return evidence


async def list_evidence_for_company(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> list[Evidence]:
    result = await db.execute(
        select(Evidence)
        .where(Evidence.tenant_id == tenant_id, Evidence.company_id == company_id)
        .order_by(Evidence.collected_at.desc())
    )
    return list(result.scalars())

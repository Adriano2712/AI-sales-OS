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


# Fase 7 (Opportunity Score 2.0): how much a single piece of evidence
# should count toward the aggregate signal balance below. UNKNOWN
# contributes nothing — the Opportunity Signal's absolute rule (Fase 3)
# extended to aggregation: absence of evidence must never tip the balance
# either way, not even by NEUTRAL/UNKNOWN evidence "diluting" the mix.
_POLARITY_CONFIDENCE_WEIGHT: dict[EvidenceConfidence, float] = {
    EvidenceConfidence.HIGH: 1.0,
    EvidenceConfidence.MEDIUM: 0.6,
    EvidenceConfidence.LOW: 0.3,
    EvidenceConfidence.UNKNOWN: 0.0,
}


def compute_signal_balance(evidence_list: list[Evidence]) -> float | None:
    """Pure — confidence-weighted balance of POSITIVE vs NEGATIVE opportunity
    signals for a company, scaled 0-100 (100 = every signal is confidently
    POSITIVE, 0 = every signal is confidently NEGATIVE). NEUTRAL and UNKNOWN
    evidence never contribute — only claims this system itself already
    classified as POSITIVE/NEGATIVE opportunity signals count, weighted by
    how confidently each was observed. Returns None (excluded from whatever
    weighted average consumes this, never a fabricated midpoint) when there
    is no confidently-polarized evidence at all — same renormalize-over-
    known-dimensions discipline as every other score in this project."""
    positive = sum(
        _POLARITY_CONFIDENCE_WEIGHT[e.confidence]
        for e in evidence_list
        if e.polarity == EvidencePolarity.POSITIVE
    )
    negative = sum(
        _POLARITY_CONFIDENCE_WEIGHT[e.confidence]
        for e in evidence_list
        if e.polarity == EvidencePolarity.NEGATIVE
    )
    total = positive + negative
    if total == 0:
        return None
    return round(100.0 * positive / total, 1)

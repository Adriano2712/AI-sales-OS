import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.evidence.enums import EvidenceConfidence
from app.modules.evidence.models import Evidence


async def get_or_create_evidence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    claim: str,
    source: str,
    confidence: EvidenceConfidence,
    source_url: str | None = None,
    supporting_data: dict | None = None,
) -> Evidence:
    """Idempotent by (tenant, company, claim): re-running enrichment for the
    same company shouldn't pile up duplicate identical claims (spec section
    54's idempotency principle, extended to evidence)."""
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

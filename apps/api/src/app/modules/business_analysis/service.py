import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_gateway.base import AIProvider
from app.modules.ai_gateway.service import run_ai_task
from app.modules.business_analysis.ai_analyst import BusinessAnalysisAIOutput, build_ai_request
from app.modules.business_analysis.models import BusinessAnalysis
from app.modules.business_analysis.scoring import compute_deterministic_scores, compute_overall_score
from app.modules.companies.models import Company
from app.modules.evidence.enums import EvidenceConfidence
from app.modules.evidence.service import get_or_create_evidence, list_evidence_for_company
from app.modules.website_analysis.service import get_latest_analysis as get_latest_website_analysis


async def get_latest_business_analysis(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> BusinessAnalysis | None:
    result = await db.execute(
        select(BusinessAnalysis)
        .where(BusinessAnalysis.tenant_id == tenant_id, BusinessAnalysis.company_id == company_id)
        .order_by(BusinessAnalysis.analyzed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def analyze_business(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company: Company,
    ai_provider: AIProvider,
) -> BusinessAnalysis:
    """Cost control (spec section 39): skip the AI call entirely if this
    company was already analyzed. Re-analysis is a deliberate future action,
    not something that happens automatically on every pipeline re-run."""
    existing = await get_latest_business_analysis(db, tenant_id, company.id)
    if existing is not None:
        return existing

    has_website = bool(company.website)
    website_analysis = (
        await get_latest_website_analysis(db, tenant_id, company.id) if has_website else None
    )
    website_digital_score = website_analysis.digital_score if website_analysis else None

    evidence_list = await list_evidence_for_company(db, tenant_id, company.id)
    has_opening_hours_evidence = any(e.claim.startswith("opening_hours:") for e in evidence_list)

    deterministic = compute_deterministic_scores(
        has_website=has_website,
        website_digital_score=website_digital_score,
        has_phone=bool(company.phone),
        has_opening_hours_evidence=has_opening_hours_evidence,
    )

    website_findings = None
    if website_analysis is not None:
        website_findings = {
            "digital_score": website_analysis.digital_score,
            "score_funcionamento": website_analysis.score_funcionamento,
            "score_mobile": website_analysis.score_mobile,
            "score_conversao": website_analysis.score_conversao,
            "score_conteudo": website_analysis.score_conteudo,
        }

    evidence_claims = [(e.claim, e.confidence.value) for e in evidence_list]

    ai_request = build_ai_request(
        company_name=company.name,
        segment=company.segment,
        city=company.city,
        state=company.state,
        digital_maturity_score=deterministic.digital_maturity_score,
        activity_score=deterministic.activity_score,
        need_score=deterministic.need_score,
        website_findings=website_findings,
        evidence_claims=evidence_claims,
    )

    ai_response = await run_ai_task(db, ai_provider, tenant_id, ai_request)
    # AIResponse.output is typed as the generic base BaseModel (the gateway
    # is provider/task-agnostic) — safe to narrow here since we're the ones
    # who set output_schema=BusinessAnalysisAIOutput on the request above,
    # and AnthropicProvider validates against exactly that schema already.
    output = cast(BusinessAnalysisAIOutput, ai_response.output)

    overall_score = compute_overall_score(
        business_fit_score=output.business_fit_score,
        activity_score=deterministic.activity_score,
        digital_maturity_score=deterministic.digital_maturity_score,
        need_score=deterministic.need_score,
        compatibility_score=output.compatibility_score,
    )

    now = datetime.now(UTC)

    # Every AI finding/problem becomes a traceable Evidence row too — the
    # analysis table's `findings`/`problems` JSON is the readable summary,
    # Evidence is the audit trail (spec sections 34/60).
    for finding in output.findings:
        await get_or_create_evidence(
            db,
            tenant_id,
            company.id,
            claim=finding,
            source="ai_analyst",
            confidence=EvidenceConfidence.MEDIUM,
            supporting_data={"kind": "finding"},
        )
    for problem in output.problems:
        await get_or_create_evidence(
            db,
            tenant_id,
            company.id,
            claim=problem,
            source="ai_analyst",
            confidence=EvidenceConfidence.MEDIUM,
            supporting_data={"kind": "problem"},
        )

    analysis = BusinessAnalysis(
        tenant_id=tenant_id,
        company_id=company.id,
        business_fit_score=float(output.business_fit_score),
        activity_score=deterministic.activity_score,
        digital_maturity_score=deterministic.digital_maturity_score,
        need_score=deterministic.need_score,
        compatibility_score=float(output.compatibility_score),
        overall_score=overall_score,
        confidence=float(output.confidence),
        findings=output.findings,
        problems=output.problems,
        analyzed_at=now,
    )
    db.add(analysis)
    await db.flush()
    return analysis

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_gateway.router import ProviderNotConfigured
from app.modules.ai_gateway.service import run_ai_task_routed
from app.modules.companies.models import Company
from app.modules.evidence.enums import EvidenceCategory, EvidenceConfidence, EvidencePolarity
from app.modules.evidence.service import get_or_create_evidence
from app.modules.website_analysis.ai_diagnostic import SiteDiagnosticAIOutput
from app.modules.website_analysis.ai_diagnostic import build_ai_request as build_diagnostic_request
from app.modules.website_analysis.crawler import WebsiteCrawler
from app.modules.website_analysis.enums import WebsiteStatus
from app.modules.website_analysis.models import Website, WebsiteAnalysis, WebsitePage
from app.modules.website_analysis.scoring import (
    compute_digital_score,
    compute_opportunity_score,
    compute_sub_scores,
    derive_problems,
)
from app.modules.website_analysis.status import CONFIDENT_QUALITY_STATUSES, derive_website_status

# Fase 5 Opportunity Signal classification for each WebsiteStatus — mirrors
# enrichment/service.py's _SUPPLEMENTARY_FIELD_SIGNAL pattern. BLOCKED/
# TIMEOUT/JS_REQUIRED/UNKNOWN are the absolute rule in table form: none of
# them are a real read on the site, so none of them get anything but
# UNKNOWN/UNKNOWN. GOOD is NEGATIVE (less room for us to help — spec's own
# "site moderno adequado" negative example); everything else that IS a real
# gap (OFFLINE/WEBSITE_NOT_FOUND/POOR/NEEDS_IMPROVEMENT — no working site is
# itself an opportunity, per spec's "sem site" positive example) is
# POSITIVE. ANALYZED is a genuine middle state — some real data, not enough
# to grade — so it's NEUTRAL, not confidently either way.
_STATUS_SIGNAL: dict[WebsiteStatus, tuple[EvidenceConfidence, EvidencePolarity]] = {
    WebsiteStatus.WEBSITE_NOT_FOUND: (EvidenceConfidence.HIGH, EvidencePolarity.POSITIVE),
    WebsiteStatus.OFFLINE: (EvidenceConfidence.HIGH, EvidencePolarity.POSITIVE),
    WebsiteStatus.POOR: (EvidenceConfidence.HIGH, EvidencePolarity.POSITIVE),
    WebsiteStatus.NEEDS_IMPROVEMENT: (EvidenceConfidence.HIGH, EvidencePolarity.POSITIVE),
    WebsiteStatus.GOOD: (EvidenceConfidence.HIGH, EvidencePolarity.NEGATIVE),
    WebsiteStatus.ANALYZED: (EvidenceConfidence.MEDIUM, EvidencePolarity.NEUTRAL),
    WebsiteStatus.BLOCKED: (EvidenceConfidence.UNKNOWN, EvidencePolarity.UNKNOWN),
    WebsiteStatus.TIMEOUT: (EvidenceConfidence.UNKNOWN, EvidencePolarity.UNKNOWN),
    WebsiteStatus.JS_REQUIRED: (EvidenceConfidence.UNKNOWN, EvidencePolarity.UNKNOWN),
    WebsiteStatus.UNKNOWN: (EvidenceConfidence.UNKNOWN, EvidencePolarity.UNKNOWN),
}


async def get_or_create_website(
    db: AsyncSession, tenant_id: uuid.UUID, company: Company
) -> Website:
    result = await db.execute(
        select(Website).where(Website.tenant_id == tenant_id, Website.company_id == company.id)
    )
    website = result.scalar_one_or_none()
    if website is not None:
        return website

    if not company.website:
        raise ValueError(f"Company {company.id} has no website to analyze")

    website = Website(tenant_id=tenant_id, company_id=company.id, url=company.website)
    db.add(website)
    await db.flush()
    return website


async def analyze_website(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    company: Company,
    crawler: WebsiteCrawler | None = None,
) -> WebsiteAnalysis:
    website = await get_or_create_website(db, tenant_id, company)

    crawler = crawler or WebsiteCrawler()
    pages = await crawler.crawl(website.url)

    # Fresh snapshot each run, not accumulating history — see WebsitePage's
    # docstring. website_analyses is the append-only historical record.
    await db.execute(delete(WebsitePage).where(WebsitePage.website_id == website.id))

    now = datetime.now(UTC)
    for page in pages:
        db.add(
            WebsitePage(
                tenant_id=tenant_id,
                website_id=website.id,
                url=page.url,
                page_type=page.page_type,
                http_status=page.http_status,
                title=page.title,
                meta_description=page.meta_description,
                has_viewport_meta=page.has_viewport_meta,
                has_contact_form=page.has_contact_form,
                has_phone_link=page.has_phone_link,
                has_email_link=page.has_email_link,
                has_whatsapp_link=page.has_whatsapp_link,
                has_nav=page.has_nav,
                has_custom_stylesheet=page.has_custom_stylesheet,
                word_count=page.word_count,
                error=page.error,
                fetched_at=now,
            )
        )

    # Real contact info found while crawling the company's own site — never
    # overwrites a value already known (same non-destructive rule as
    # companies/service.py's merge_missing_fields, just from a different
    # source: the crawl itself, not a discovery provider).
    if not company.email:
        found_email = next((page.email for page in pages if page.email), None)
        if found_email:
            company.email = found_email
            # Real gap found during the automation-planning session: every
            # other core field (phone/website/instagram) gets an
            # auditable Evidence row when found, via enrichment's
            # _record_core_field_evidence — this fill happens later (after
            # discovery's own enrich_company already ran and recorded an
            # UNKNOWN claim for email, since no site had been fetched yet)
            # and was leaving no trail at all. A distinct claim, kept side
            # by side with that earlier UNKNOWN one rather than overwriting
            # it — an honest record of what was known at each point.
            await get_or_create_evidence(
                db,
                tenant_id,
                company.id,
                claim=f"email (via site): {found_email}",
                source="website_crawler",
                confidence=EvidenceConfidence.HIGH,
                polarity=EvidencePolarity.POSITIVE,
                category=EvidenceCategory.CONTACTABILITY,
                source_url=website.url,
                supporting_data={"field": "email", "value": found_email},
            )

    sub_scores = compute_sub_scores(pages)
    raw_quality_score = compute_digital_score(sub_scores)
    status = derive_website_status(pages, sub_scores, raw_quality_score)

    # The absolute rule, closed at the score level too: compute_sub_scores
    # can still mechanically produce a low-but-real-looking number from a
    # JS-only shell's near-empty HTML (or similar partial data) even though
    # status already says "we didn't really see this site" — never let that
    # number leak out and silently contradict the status (a real bug caught
    # in this phase's own end-to-end validation, not by a unit test: see
    # docs/WEBSITE_ANALYSIS.md's Fase 5 section).
    if status in CONFIDENT_QUALITY_STATUSES:
        digital_score = raw_quality_score
        opportunity_score = compute_opportunity_score(sub_scores)
    else:
        digital_score = None
        opportunity_score = None
    problems = derive_problems(pages, status)

    status_confidence, status_polarity = _STATUS_SIGNAL[status]
    await get_or_create_evidence(
        db,
        tenant_id,
        company.id,
        claim=f"Website status: {status.value}",
        source="website_analysis",
        confidence=status_confidence,
        polarity=status_polarity,
        category=EvidenceCategory.WEBSITE_QUALITY,
        source_url=website.url,
        supporting_data={"field": "website_status", "status": status.value},
    )

    ai_diagnostic: str | None = None
    # Cost control (spec section 39): only spend on a paragraph when the
    # homepage actually loaded — a fully down site is already self-
    # explanatory (see derive_problems), an AI paragraph would add cost
    # without adding signal. Unlike business_analysis/message_generation,
    # a missing/unconfigured provider degrades gracefully here instead of
    # aborting — the deterministic score/problems are the core feature and
    # must never depend on AI being configured (see jobs/handlers/website_analysis.py).
    if digital_score is not None:
        ai_request = build_diagnostic_request(
            company_name=company.name,
            segment=company.segment,
            digital_score=digital_score,
            problems=problems,
        )
        try:
            ai_response = await run_ai_task_routed(db, tenant_id, ai_request)
        except ProviderNotConfigured:
            ai_diagnostic = None
        else:
            # Safe narrowing: we set output_schema=SiteDiagnosticAIOutput
            # above, and the provider validates against exactly that schema.
            ai_diagnostic = cast(SiteDiagnosticAIOutput, ai_response.output).business_impact

    analysis = WebsiteAnalysis(
        tenant_id=tenant_id,
        website_id=website.id,
        status=status,
        digital_score=digital_score,
        opportunity_score=opportunity_score,
        score_funcionamento=sub_scores.funcionamento,
        score_mobile=sub_scores.mobile,
        score_ux=sub_scores.ux,
        score_conversao=sub_scores.conversao,
        score_conteudo=sub_scores.conteudo,
        score_design=sub_scores.design,
        findings={
            "pages_crawled": len(pages),
            "pages": [{"url": p.url, "type": p.page_type.value, "status": p.http_status} for p in pages],
            "status": status.value,
            "problems": problems,
            "ai_diagnostic": ai_diagnostic,
        },
        analyzed_at=now,
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def get_latest_analysis(
    db: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> WebsiteAnalysis | None:
    result = await db.execute(
        select(WebsiteAnalysis)
        .join(Website, Website.id == WebsiteAnalysis.website_id)
        .where(Website.tenant_id == tenant_id, Website.company_id == company_id)
        .order_by(WebsiteAnalysis.analyzed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

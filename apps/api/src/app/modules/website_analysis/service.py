import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.companies.models import Company
from app.modules.website_analysis.crawler import WebsiteCrawler
from app.modules.website_analysis.models import Website, WebsiteAnalysis, WebsitePage
from app.modules.website_analysis.scoring import compute_digital_score, compute_sub_scores


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

    sub_scores = compute_sub_scores(pages)
    digital_score = compute_digital_score(sub_scores)

    analysis = WebsiteAnalysis(
        tenant_id=tenant_id,
        website_id=website.id,
        digital_score=digital_score,
        score_funcionamento=sub_scores.funcionamento,
        score_mobile=sub_scores.mobile,
        score_ux=sub_scores.ux,
        score_conversao=sub_scores.conversao,
        score_conteudo=sub_scores.conteudo,
        score_design=sub_scores.design,
        findings={
            "pages_crawled": len(pages),
            "pages": [{"url": p.url, "type": p.page_type.value, "status": p.http_status} for p in pages],
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

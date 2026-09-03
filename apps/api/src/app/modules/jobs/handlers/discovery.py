import asyncio
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.campaigns.enums import CampaignRunStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.service import MatchConfidence, NormalizedRawCompany, upsert_company_from_raw
from app.modules.discovery.base import DiscoveryProvider, DiscoveryProviderError
from app.modules.discovery.providers.apify import ApifyProvider
from app.modules.discovery.providers.overpass import OverpassProvider
from app.modules.enrichment.service import enrich_company
from app.modules.jobs.async_entrypoint import run_job_sync
from app.modules.jobs.enums import JobType
from app.modules.jobs.models import Job
from app.modules.jobs.queue import get_queue
from app.modules.jobs.service import get_or_create_job, mark_completed, mark_failed, mark_running

logger = get_logger(job_type="DISCOVERY")

# Overpass's shared public instance rate-limits back-to-back requests (429,
# confirmed against the real API — see docs/DISCOVERY.md). A campaign spans
# multiple cities per run, each a separate request; this spaces them out
# rather than burning through every city's slot on the first 429. Doesn't
# eliminate rate limiting under real load (Fase 9's ~9 segment x city
# combinations), just reduces it — a dedicated/paid Overpass instance would
# be the real fix if this proves insufficient. Apify isn't subject to this
# (separate, paid, per-account rate limit) — it runs concurrently with
# Overpass within the same city, not staggered by this delay.
_PROVIDER_REQUEST_DELAY_SECONDS = 2.0


def split_target(total: int, n: int) -> list[int]:
    """Divides `total` as evenly as possible across `n` buckets, remainder
    going to the first ones — the ~33/33/34 split from spec section 9's
    example. Pure function, unit tested directly."""
    if n <= 0:
        return []
    base, remainder = divmod(total, n)
    return [base + 1 if i < remainder else base for i in range(n)]


def build_providers() -> list[DiscoveryProvider]:
    """OSM/Overpass always runs. Apify is added only when configured
    (settings.apify_api_token) — the system degrades to OSM-only rather than
    failing when it isn't, same optional-provider pattern the AI Gateway
    already uses for anthropic_api_key."""
    providers: list[DiscoveryProvider] = [OverpassProvider()]
    settings = get_settings()
    if settings.apify_api_token:
        providers.append(
            ApifyProvider(
                api_token=settings.apify_api_token, actor_id=settings.apify_discovery_actor
            )
        )
    else:
        logger.info("discovery_apify_not_configured")
    return providers


async def _search_one_provider(
    provider: DiscoveryProvider, segment: str, city: str, state: str, country: str, limit: int
) -> tuple[str, list[NormalizedRawCompany], DiscoveryProviderError | None]:
    """Isolates one provider's failure from the others (spec section 28
    fallback) — returned as data rather than raised, so `asyncio.gather`
    below never has to special-case which provider broke."""
    try:
        results = await provider.search(segment, city, state, country, limit)
        return provider.name, results, None
    except DiscoveryProviderError as exc:
        return provider.name, [], exc


async def _run(job_id: str, tenant_id: str, campaign_run_id: str) -> None:
    tenant_uuid = uuid.UUID(tenant_id)
    run_uuid = uuid.UUID(campaign_run_id)
    job_uuid = uuid.UUID(job_id)
    providers = build_providers()

    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_uuid)

        job = await db.get(Job, job_uuid)
        run = await db.get(CampaignRun, run_uuid)
        if job is None or run is None:
            logger.error("discovery_job_or_run_not_found", job_id=job_id, run_id=campaign_run_id)
            return

        campaign = await db.get(Campaign, run.campaign_id)
        if campaign is None:
            logger.error("discovery_campaign_not_found", campaign_id=str(run.campaign_id))
            await mark_failed(db, job, error="campaign not found", retryable=False)
            await db.commit()
            return

        await mark_running(db, job)
        run.status = CampaignRunStatus.RUNNING
        await db.commit()

        per_city_targets = split_target(campaign.target_quantity, len(campaign.cities))
        errors: list[dict] = []
        found = 0
        validated = 0
        duplicates = 0
        enriched = 0
        analyzed = 0

        for index, (city, city_target) in enumerate(
            zip(campaign.cities, per_city_targets, strict=True)
        ):
            if index > 0:
                await asyncio.sleep(_PROVIDER_REQUEST_DELAY_SECONDS)

            # OSM and Apify run concurrently for this city (spec section 8 —
            # neither should wait on the other), each caps its own result
            # count at city_target; overlap between them is resolved by the
            # identity-resolution/merge step below, not by pre-splitting the
            # target between providers.
            await set_tenant_context(db, tenant_uuid)
            provider_results = await asyncio.gather(
                *[
                    _search_one_provider(
                        provider, campaign.segment, city, campaign.state, campaign.country, city_target
                    )
                    for provider in providers
                ]
            )

            raw_companies: list[NormalizedRawCompany] = []
            for provider_name, results, error in provider_results:
                if error is not None:
                    # One provider's city failure doesn't kill the other
                    # provider's results for that city, nor the rest of the
                    # run (spec sections 28, 55).
                    errors.append({"city": city, "provider": provider_name, "error": str(error)})
                    logger.error(
                        "discovery_provider_failed", city=city, provider=provider_name, error=str(error)
                    )
                    continue
                logger.info(
                    "discovery_provider_completed",
                    city=city,
                    provider=provider_name,
                    count=len(results),
                )
                raw_companies.extend(results)

            found += len(raw_companies)
            for raw in raw_companies:
                try:
                    await set_tenant_context(db, tenant_uuid)
                    company, confidence = await upsert_company_from_raw(db, tenant_uuid, raw)
                    validated += 1
                    if confidence == MatchConfidence.HIGH:
                        duplicates += 1

                    # No extra network call here — enrich_company reads the
                    # raw provider data discovery already fetched
                    # (CompanySource.data), so doing it inline is cheap. See
                    # enrichment/service.py.
                    await enrich_company(db, tenant_uuid, company)
                    enriched += 1

                    await db.commit()

                    if company.website:
                        # Real network I/O against a third-party site — kept
                        # as its own queued job (unlike enrichment) so one
                        # slow/broken website can't stall discovery for the
                        # rest of the campaign. See jobs/handlers/website_analysis.py.
                        await set_tenant_context(db, tenant_uuid)
                        analysis_job = await get_or_create_job(
                            db,
                            tenant_id=tenant_uuid,
                            job_type=JobType.WEBSITE_ANALYSIS,
                            idempotency_key=str(company.id),
                            payload={"company_id": str(company.id)},
                        )
                        await db.commit()
                        get_queue().enqueue(
                            "app.modules.jobs.handlers.website_analysis.run",
                            str(analysis_job.id),
                            str(tenant_uuid),
                            str(company.id),
                        )
                        # Business analysis waits for website_analysis to
                        # finish in this case — see that handler, which
                        # enqueues it itself once a fresh digital_score
                        # exists to feed the AI Analyst.
                    else:
                        await set_tenant_context(db, tenant_uuid)
                        business_job = await get_or_create_job(
                            db,
                            tenant_id=tenant_uuid,
                            job_type=JobType.BUSINESS_ANALYSIS,
                            idempotency_key=str(company.id),
                            payload={"company_id": str(company.id)},
                        )
                        await db.commit()
                        get_queue().enqueue(
                            "app.modules.jobs.handlers.business_analysis.run",
                            str(business_job.id),
                            str(tenant_uuid),
                            str(company.id),
                        )
                        analyzed += 1
                except Exception as exc:  # noqa: BLE001 - one bad record shouldn't kill the run
                    await db.rollback()
                    errors.append({"city": city, "company": raw.name, "error": str(exc)})
                    logger.error(
                        "discovery_company_failed", city=city, name=raw.name, error=str(exc)
                    )

        # Re-fetch rather than reuse the earlier references: a company-upsert
        # failure above calls db.rollback(), which SQLAlchemy conservatively
        # expires the whole session's identity map for — the earlier `run`/
        # `job` objects may no longer be safely usable without a fresh load.
        await set_tenant_context(db, tenant_uuid)
        run = await db.get(CampaignRun, run_uuid)
        job = await db.get(Job, job_uuid)
        if run is None or job is None:
            logger.error("discovery_run_or_job_vanished", job_id=job_id, run_id=campaign_run_id)
            return

        run.status = CampaignRunStatus.COMPLETED
        run.finished_at = datetime.now(UTC)
        run.companies_found = found
        run.companies_validated = validated
        run.duplicates = duplicates
        run.enriched = enriched
        # Known undercount: only companies without a website get their
        # BUSINESS_ANALYSIS job enqueued from here. For companies with a
        # website, jobs/handlers/website_analysis.py enqueues it after the
        # crawl completes (it doesn't know which campaign_run triggered it,
        # so it can't increment this counter). Real progress lives in the
        # `jobs` table either way — this field is a rough summary, not an
        # authoritative count.
        run.analyzed = analyzed
        run.errors = errors

        await mark_completed(
            db, job, result={"companies_found": found, "duplicates": duplicates}
        )
        await db.commit()


def run(job_id: str, tenant_id: str, campaign_run_id: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    handlers/ping.py."""
    run_job_sync(_run(job_id, tenant_id, campaign_run_id))

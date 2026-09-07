import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import async_session_factory, set_tenant_context
from app.core.logging import get_logger
from app.modules.campaigns.enums import CampaignRunStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
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
from app.modules.opportunities.models import Opportunity

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

# Fase 8 (Smart Refill). Bounded — a campaign that's genuinely out of real
# supply in its configured cities shouldn't hammer providers indefinitely
# (spec: never run large batches in production during testing, extended
# here to "never run unbounded batches at all"). Each pass multiplies the
# original per-city target rather than adding a small fixed amount, so a
# badly-undershooting campaign gets a real second attempt at real supply,
# not a token gesture.
_MAX_REFILL_PASSES = 2


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


@dataclass
class _PassResult:
    """One city's worth of search+upsert+enrich+chain — the original
    single-pass loop body extracted so Fase 8's refill can call it again
    with a higher limit without duplicating the logic."""

    found: int = 0
    validated: int = 0
    duplicates: int = 0
    enriched: int = 0
    analyzed: int = 0
    company_ids: list[uuid.UUID] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


async def _discover_and_process_city(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    campaign: Campaign,
    run_uuid: uuid.UUID,
    city: str,
    city_limit: int,
    providers: list[DiscoveryProvider],
) -> _PassResult:
    result = _PassResult()

    # OSM and Apify run concurrently for this city (spec section 8 — neither
    # should wait on the other), each caps its own result count at
    # city_limit; overlap between them is resolved by the identity-
    # resolution/merge step below, not by pre-splitting the target between
    # providers.
    await set_tenant_context(db, tenant_uuid)
    provider_results = await asyncio.gather(
        *[
            _search_one_provider(
                provider, campaign.segment, city, campaign.state, campaign.country, city_limit
            )
            for provider in providers
        ]
    )

    raw_companies: list[NormalizedRawCompany] = []
    for provider_name, results, error in provider_results:
        if error is not None:
            # One provider's city failure doesn't kill the other provider's
            # results for that city, nor the rest of the run (spec sections
            # 28, 55).
            result.errors.append({"city": city, "provider": provider_name, "error": str(error)})
            logger.error(
                "discovery_provider_failed", city=city, provider=provider_name, error=str(error)
            )
            continue
        logger.info(
            "discovery_provider_completed", city=city, provider=provider_name, count=len(results)
        )
        raw_companies.extend(results)

    result.found = len(raw_companies)
    for raw in raw_companies:
        try:
            await set_tenant_context(db, tenant_uuid)
            company, confidence = await upsert_company_from_raw(
                db, tenant_uuid, raw, campaign_run_id=run_uuid
            )
            result.validated += 1
            if confidence == MatchConfidence.HIGH:
                result.duplicates += 1
            result.company_ids.append(company.id)

            # No extra network call here — enrich_company reads the raw
            # provider data discovery already fetched (CompanySource.data),
            # so doing it inline is cheap. See enrichment/service.py.
            await enrich_company(db, tenant_uuid, company)
            result.enriched += 1

            await db.commit()

            if company.website:
                # Real network I/O against a third-party site — kept as its
                # own queued job (unlike enrichment) so one slow/broken
                # website can't stall discovery for the rest of the
                # campaign. See jobs/handlers/website_analysis.py.
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
                # Business analysis waits for website_analysis to finish in
                # this case — see that handler, which enqueues it itself
                # once a fresh digital_score exists to feed the AI Analyst.
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
                result.analyzed += 1
        except Exception as exc:  # noqa: BLE001 - one bad record shouldn't kill the run
            await db.rollback()
            result.errors.append({"city": city, "company": raw.name, "error": str(exc)})
            logger.error("discovery_company_failed", city=city, name=raw.name, error=str(exc))

    return result


async def _count_usable_companies(
    db: AsyncSession, tenant_id: uuid.UUID, company_ids: list[uuid.UUID]
) -> tuple[int, int]:
    """Fase 8 (Smart Refill): "usable" means workable toward this campaign's
    target_quantity — not CompanyStatus.INVALID (spec's "apparently closed
    business"), not do_not_contact, and critically not already-contacted
    (an Opportunity with a tracked outcome anywhere in the tenant — outcome
    isn't ordered, spec section-confirmed no send/reply integration exists
    yet, so `outcome is not None` is the only reliable "something happened"
    check). This is deliberately tenant-wide, not scoped to this campaign
    run — a company a different campaign already contacted must not read as
    a fresh, workable lead just because this campaign rediscovered it (the
    same cross-campaign identity resolution upsert_company_from_raw already
    does for raw data). Returns (usable_count, skipped_count)."""
    if not company_ids:
        return 0, 0
    unique_ids = list(set(company_ids))
    workable_result = await db.execute(
        select(Company.id).where(
            Company.tenant_id == tenant_id,
            Company.id.in_(unique_ids),
            Company.status != CompanyStatus.INVALID,
            Company.do_not_contact.is_(False),
        )
    )
    workable_ids = {row[0] for row in workable_result.all()}
    if not workable_ids:
        return 0, len(unique_ids)

    contacted_result = await db.execute(
        select(Opportunity.company_id)
        .where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.company_id.in_(workable_ids),
            Opportunity.outcome.isnot(None),
        )
        .distinct()
    )
    already_contacted_ids = {row[0] for row in contacted_result.all()}
    usable = len(workable_ids) - len(already_contacted_ids)
    return usable, len(unique_ids) - usable


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
        touched_company_ids: list[uuid.UUID] = []

        for index, (city, city_target) in enumerate(
            zip(campaign.cities, per_city_targets, strict=True)
        ):
            if index > 0:
                await asyncio.sleep(_PROVIDER_REQUEST_DELAY_SECONDS)
            pass_result = await _discover_and_process_city(
                db, tenant_uuid, campaign, run_uuid, city, city_target, providers
            )
            found += pass_result.found
            validated += pass_result.validated
            duplicates += pass_result.duplicates
            enriched += pass_result.enriched
            analyzed += pass_result.analyzed
            touched_company_ids.extend(pass_result.company_ids)
            errors.extend(pass_result.errors)

        # Fase 8: Smart Refill. companies_found/validated/duplicates/
        # enriched/analyzed above stay exactly what the original single pass
        # produced (API/dashboard backward-compatibility) — refill activity
        # is tracked in its own fields below, never folded back into those.
        # Only fires when the campaign's real, workable supply (not
        # INVALID/do-not-contact/already-contacted — spec's own "skip
        # already-contacted/duplicate leads") actually falls short of
        # target_quantity; a run that already hit its target makes zero
        # extra provider calls.
        refill_attempts = 0
        refill_found = 0
        # SET LOCAL is transaction-scoped — the last company's db.commit()
        # above ended the transaction it was set in, so it must be set again
        # before this query (same recurring gotcha as everywhere else in
        # this codebase that re-queries after a commit).
        await set_tenant_context(db, tenant_uuid)
        usable_found, skipped_already_contacted = await _count_usable_companies(
            db, tenant_uuid, touched_company_ids
        )
        seen_company_ids = set(touched_company_ids)
        while usable_found < campaign.target_quantity and refill_attempts < _MAX_REFILL_PASSES:
            refill_attempts += 1
            # Overpass returns the same query's full result set regardless
            # of `limit` (only local truncation changes) and Apify's actor
            # genuinely crawls more when asked — multiplying the original
            # per-city target gives both providers a real shot at surfacing
            # results the first pass's lower limit truncated away, not just
            # re-fetching what's already known (see docs/DISCOVERY.md).
            expanded_targets = [t * (refill_attempts + 1) for t in per_city_targets]
            pass_found_new = False
            for index, (city, city_limit) in enumerate(
                zip(campaign.cities, expanded_targets, strict=True)
            ):
                await asyncio.sleep(_PROVIDER_REQUEST_DELAY_SECONDS)
                pass_result = await _discover_and_process_city(
                    db, tenant_uuid, campaign, run_uuid, city, city_limit, providers
                )
                refill_found += pass_result.found
                errors.extend(pass_result.errors)
                for company_id in pass_result.company_ids:
                    if company_id not in seen_company_ids:
                        pass_found_new = True
                    seen_company_ids.add(company_id)

            if not pass_found_new:
                # Providers are exhausted for these exact cities — another
                # pass would just re-process what's already known. Stop
                # rather than burn more requests for zero gain.
                logger.info(
                    "discovery_refill_exhausted", run_id=campaign_run_id, attempt=refill_attempts
                )
                break

            await set_tenant_context(db, tenant_uuid)
            usable_found, skipped_already_contacted = await _count_usable_companies(
                db, tenant_uuid, list(seen_company_ids)
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
        run.refill_attempts = refill_attempts
        run.refill_companies_found = refill_found
        run.usable_found = usable_found
        run.skipped_already_contacted = skipped_already_contacted

        await mark_completed(
            db,
            job,
            result={
                "companies_found": found,
                "duplicates": duplicates,
                "usable_found": usable_found,
                "refill_attempts": refill_attempts,
            },
        )
        await db.commit()


def run(job_id: str, tenant_id: str, campaign_run_id: str) -> None:
    """RQ entrypoint — bridges into the app's async DB layer, same pattern as
    handlers/ping.py."""
    run_job_sync(_run(job_id, tenant_id, campaign_run_id))

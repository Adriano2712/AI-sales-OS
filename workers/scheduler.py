"""Daily scheduled discovery + digest email, and a stuck-job retry sweep.

A separate, optional 4th local process (alongside API + worker + web).
Two independent jobs share this loop:
  1. Daily discovery/digest — only if DAILY_DISCOVERY_TENANT_ID is set (see
     docs/DAILY_DIGEST.md).
  2. Retrying jobs stuck RETRYING (see _RETRYABLE_JOB_HANDLERS below) —
     runs for every tenant regardless of (1), since job-retry reliability
     isn't specific to the daily-digest feature.
Stateless across restarts: every tick re-derives what's due from the
database and audit_log, never from in-memory state, so killing and
restarting this process never double-sends a digest, re-retries a job past
its attempt cap, or loses track of "did today's run happen yet."

Usage:
    apps/api/.venv/Scripts/python workers/scheduler.py
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from sqlalchemy import select  # noqa: E402

from app.core import model_registry  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.db import async_session_factory, set_tenant_context  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.modules.audit.enums import AuditEventType  # noqa: E402
from app.modules.audit.models import AuditLog  # noqa: E402
from app.modules.audit.service import log_event  # noqa: E402
from app.modules.business_analysis.service import get_latest_business_analysis  # noqa: E402
from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus  # noqa: E402
from app.modules.campaigns.models import Campaign, CampaignRun  # noqa: E402
from app.modules.campaigns.schemas import CampaignCreate, CampaignUpdate  # noqa: E402
from app.modules.campaigns.service import create_campaign, create_run, update_campaign  # noqa: E402
from app.modules.companies.models import Company  # noqa: E402
from app.modules.discovery.base import NATIONWIDE_CITY_SENTINEL  # noqa: E402
from app.modules.jobs.enums import JobStatus, JobType  # noqa: E402
from app.modules.jobs.models import Job  # noqa: E402
from app.modules.jobs.queue import get_queue  # noqa: E402
from app.modules.jobs.service import get_or_create_job, mark_failed  # noqa: E402
from app.modules.notifications.digest import (  # noqa: E402
    DigestCompanyEntry,
    build_digest_html,
    build_digest_subject,
    build_digest_text,
)
from app.modules.notifications.email_sender import EmailSendError, send_email  # noqa: E402
from app.modules.notifications.site_digest import (  # noqa: E402
    SiteDiagnosticEntry,
    build_site_digest_html,
    build_site_digest_subject,
    build_site_digest_text,
)
from app.modules.opportunities.models import Opportunity  # noqa: E402
from app.modules.tenancy.models import Tenant  # noqa: E402
from app.modules.website_analysis.service import (  # noqa: E402
    get_latest_analysis as get_latest_website_analysis,
)

logger = get_logger(job_type="SCHEDULER")

_TZ = ZoneInfo("America/Sao_Paulo")
# Rotates so a fixed small daily quantity still covers all three pilot
# segments over time, rather than hammering one — user's explicit choice.
_SEGMENTS_ROTATION = ["restaurants", "clinics", "b2b_services"]
_DAILY_TARGET_QUANTITY = 5
_CHECK_INTERVAL_SECONDS = 900  # 15 min
_DIGEST_DELAY = timedelta(minutes=30)
_CAMPAIGN_NAME_PREFIX = "Descoberta Diária (auto)"

# Real infra gap this closes (found during Fase 9 real validation runs,
# twice): every job handler catches its own AI/schema errors and calls
# mark_failed() internally rather than letting the exception propagate to
# RQ — so RQ always sees a "successful" job run even when the business
# logic inside actually failed, and RQ's own retry mechanism never
# triggers. A job marked RETRYING therefore sat there forever until a
# human noticed and manually reset it. Each entry maps a retryable JobType
# to (its RQ task path, the ordered payload keys its run() needs after
# job_id/tenant_id) — every handler's payload already carries exactly what
# its own run() signature needs (see jobs/handlers/*.py).
_MAX_JOB_ATTEMPTS = 3
_RETRYABLE_JOB_HANDLERS: dict[JobType, tuple[str, list[str]]] = {
    JobType.DISCOVERY: ("app.modules.jobs.handlers.discovery.run", ["campaign_run_id"]),
    JobType.WEBSITE_ANALYSIS: ("app.modules.jobs.handlers.website_analysis.run", ["company_id"]),
    JobType.BUSINESS_ANALYSIS: ("app.modules.jobs.handlers.business_analysis.run", ["company_id"]),
    JobType.SCORING: ("app.modules.jobs.handlers.scoring.run", ["company_id"]),
    JobType.MESSAGE_GENERATION: (
        "app.modules.jobs.handlers.message_generation.run",
        ["opportunity_id", "channel", "language"],
    ),
}


def _today_segment() -> str:
    return _SEGMENTS_ROTATION[datetime.now(_TZ).toordinal() % len(_SEGMENTS_ROTATION)]


async def _get_or_create_daily_campaign(db, tenant_id: uuid.UUID, segment: str) -> Campaign:
    name = f"{_CAMPAIGN_NAME_PREFIX} - {segment}"
    result = await db.execute(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.name == name)
    )
    campaign = result.scalar_one_or_none()
    if campaign is not None:
        if campaign.status != CampaignStatus.ACTIVE:
            campaign = await update_campaign(db, campaign, CampaignUpdate(status=CampaignStatus.ACTIVE))
        return campaign

    campaign = await create_campaign(
        db,
        tenant_id,
        CampaignCreate(
            name=name,
            segment=segment,
            # Nationwide sentinel — only Apify actually searches this (spec
            # comment in discovery/base.py); Overpass fails cleanly per city
            # and the run still succeeds via the existing fallback.
            cities=[NATIONWIDE_CITY_SENTINEL],
            state="BR",
            country="BR",
            target_quantity=_DAILY_TARGET_QUANTITY,
        ),
    )
    return await update_campaign(db, campaign, CampaignUpdate(status=CampaignStatus.ACTIVE))


async def _ensure_todays_run(db, tenant_id: uuid.UUID, campaign: Campaign) -> CampaignRun | None:
    """Returns the newly created run if today's hasn't happened yet, else
    None. Checking by `started_at`'s local date (not counting rows) is what
    makes this safe to call every 15 minutes without double-triggering."""
    today = datetime.now(_TZ).date()
    result = await db.execute(
        select(CampaignRun).where(
            CampaignRun.tenant_id == tenant_id, CampaignRun.campaign_id == campaign.id
        )
    )
    for run in result.scalars():
        if run.started_at and run.started_at.astimezone(_TZ).date() == today:
            return None

    return await create_run(db, campaign)


async def _digest_already_sent(db, tenant_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    # Same self-contained re-set as _send_digest_for_run — safe regardless
    # of what committed before this call in the caller's loop.
    await set_tenant_context(db, tenant_id)
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.event_type == AuditEventType.DAILY_DIGEST_SENT.value,
        )
    )
    return any(row.payload.get("campaign_run_id") == str(run_id) for row in result.scalars())


async def _send_digest_for_run(db, tenant_id: uuid.UUID, run: CampaignRun, campaign: Campaign) -> None:
    # Self-contained re-set rather than trusting the caller — this can run
    # as the Nth iteration of _maybe_send_pending_digests' loop, after a
    # prior iteration's own commit already reset the transaction-scoped
    # SET LOCAL (the same gotcha this project has hit before: RLS context
    # doesn't survive a commit).
    await set_tenant_context(db, tenant_id)
    result = await db.execute(select(Company).where(Company.campaign_run_id == run.id))
    companies = result.scalars().all()

    entries: list[DigestCompanyEntry] = []
    for company in companies:
        analysis = await get_latest_business_analysis(db, tenant_id, company.id)
        opp_result = await db.execute(
            select(Opportunity).where(Opportunity.company_id == company.id).limit(1)
        )
        opportunity = opp_result.scalar_one_or_none()
        entries.append(
            DigestCompanyEntry(
                name=company.name,
                segment=company.segment,
                city=company.city,
                state=company.state,
                phone=company.phone,
                website=company.website,
                overall_score=analysis.overall_score if analysis else None,
                classification=(
                    opportunity.classification.value
                    if opportunity and opportunity.classification
                    else None
                ),
            )
        )

    date_str = run.started_at.astimezone(_TZ).strftime("%d/%m/%Y") if run.started_at else "—"
    settings = get_settings()
    subject = build_digest_subject(date_str, campaign.segment, len(entries))
    text_body = build_digest_text(entries, date_str, campaign.segment)
    html_body = build_digest_html(entries, date_str, campaign.segment)

    assert settings.gmail_smtp_user and settings.gmail_smtp_app_password
    assert settings.daily_digest_recipient_email
    try:
        await asyncio.to_thread(
            send_email,
            settings.gmail_smtp_user,
            settings.gmail_smtp_app_password,
            settings.daily_digest_recipient_email,
            subject,
            text_body,
            html_body,
        )
    except EmailSendError as exc:
        logger.error("scheduler_digest_send_failed", run_id=str(run.id), error=str(exc))
        return  # not marked sent — retried automatically next tick

    await log_event(
        db,
        tenant_id,
        AuditEventType.DAILY_DIGEST_SENT,
        {"campaign_run_id": str(run.id), "companies": len(entries)},
    )
    await db.commit()
    logger.info("scheduler_digest_sent", run_id=str(run.id), companies=len(entries))


async def _site_diagnostic_already_sent(db, tenant_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    await set_tenant_context(db, tenant_id)
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.event_type == AuditEventType.DAILY_SITE_DIAGNOSTIC_SENT.value,
        )
    )
    return any(row.payload.get("campaign_run_id") == str(run_id) for row in result.scalars())


async def _send_site_diagnostic_for_run(
    db, tenant_id: uuid.UUID, run: CampaignRun, campaign: Campaign
) -> None:
    """Second, independent email — pure site diagnostics (spec: the
    differentiator), tracked by its own audit event so it can succeed or
    fail without affecting the business-summary digest sent alongside it."""
    await set_tenant_context(db, tenant_id)
    result = await db.execute(select(Company).where(Company.campaign_run_id == run.id))
    companies = result.scalars().all()

    entries: list[SiteDiagnosticEntry] = []
    for company in companies:
        if not company.website:
            entries.append(
                SiteDiagnosticEntry(
                    name=company.name,
                    city=company.city,
                    state=company.state,
                    website=None,
                    digital_score=None,
                )
            )
            continue

        analysis = await get_latest_website_analysis(db, tenant_id, company.id)
        entries.append(
            SiteDiagnosticEntry(
                name=company.name,
                city=company.city,
                state=company.state,
                website=company.website,
                digital_score=analysis.digital_score if analysis else None,
                problems=(analysis.findings.get("problems") or []) if analysis else [],
                ai_diagnostic=(analysis.findings.get("ai_diagnostic") if analysis else None),
            )
        )

    date_str = run.started_at.astimezone(_TZ).strftime("%d/%m/%Y") if run.started_at else "—"
    settings = get_settings()
    subject = build_site_digest_subject(date_str, campaign.segment, len(entries))
    text_body = build_site_digest_text(entries, date_str, campaign.segment)
    html_body = build_site_digest_html(entries, date_str, campaign.segment)

    assert settings.gmail_smtp_user and settings.gmail_smtp_app_password
    assert settings.daily_digest_recipient_email
    try:
        await asyncio.to_thread(
            send_email,
            settings.gmail_smtp_user,
            settings.gmail_smtp_app_password,
            settings.daily_digest_recipient_email,
            subject,
            text_body,
            html_body,
        )
    except EmailSendError as exc:
        logger.error("scheduler_site_diagnostic_send_failed", run_id=str(run.id), error=str(exc))
        return  # not marked sent — retried automatically next tick

    await log_event(
        db,
        tenant_id,
        AuditEventType.DAILY_SITE_DIAGNOSTIC_SENT,
        {"campaign_run_id": str(run.id), "companies": len(entries)},
    )
    await db.commit()
    logger.info("scheduler_site_diagnostic_sent", run_id=str(run.id), companies=len(entries))


async def _maybe_send_pending_digests(db, tenant_id: uuid.UUID) -> None:
    settings = get_settings()
    if not (
        settings.gmail_smtp_user
        and settings.gmail_smtp_app_password
        and settings.daily_digest_recipient_email
    ):
        logger.info("scheduler_digest_not_configured")
        return

    cutoff = datetime.now(UTC) - _DIGEST_DELAY
    result = await db.execute(
        select(CampaignRun, Campaign)
        .join(Campaign, CampaignRun.campaign_id == Campaign.id)
        .where(
            CampaignRun.tenant_id == tenant_id,
            Campaign.name.like(f"{_CAMPAIGN_NAME_PREFIX}%"),
            CampaignRun.status == CampaignRunStatus.COMPLETED,
            CampaignRun.started_at <= cutoff,
        )
    )
    for run, campaign in result.all():
        # Independent per-email idempotency checks — a failure sending one
        # (e.g. a transient SMTP error) must not block or duplicate the
        # other on the next tick.
        if not await _digest_already_sent(db, tenant_id, run.id):
            await _send_digest_for_run(db, tenant_id, run, campaign)
        if not await _site_diagnostic_already_sent(db, tenant_id, run.id):
            await _send_site_diagnostic_for_run(db, tenant_id, run, campaign)


async def _retry_stuck_jobs(db, tenant_id: uuid.UUID) -> None:
    """The actual fix — see _RETRYABLE_JOB_HANDLERS' comment above for why
    nothing else in the system ever revisits a RETRYING job on its own."""
    await set_tenant_context(db, tenant_id)
    result = await db.execute(
        select(Job).where(Job.tenant_id == tenant_id, Job.status == JobStatus.RETRYING)
    )
    stuck_jobs = list(result.scalars())

    for job in stuck_jobs:
        await set_tenant_context(db, tenant_id)

        if job.attempts >= _MAX_JOB_ATTEMPTS:
            # Give up for real rather than leaving it RETRYING forever —
            # FAILED is terminal and visible, not silent limbo.
            await mark_failed(db, job, error=job.error or "max retries exceeded", retryable=False)
            await db.commit()
            logger.error(
                "scheduler_job_gave_up",
                job_id=str(job.id),
                job_type=job.type.value,
                attempts=job.attempts,
            )
            continue

        handler = _RETRYABLE_JOB_HANDLERS.get(job.type)
        if handler is None:
            continue  # e.g. PING — not worth wiring up a retry path for
        task_path, payload_keys = handler
        try:
            extra_args = [str(job.payload[key]) for key in payload_keys]
        except KeyError:
            logger.error(
                "scheduler_retry_missing_payload", job_id=str(job.id), job_type=job.type.value
            )
            continue

        job.status = JobStatus.PENDING
        job.error = None
        await db.flush()
        await db.commit()
        get_queue().enqueue(task_path, str(job.id), str(tenant_id), *extra_args)
        logger.info(
            "scheduler_retried_job", job_id=str(job.id), job_type=job.type.value, attempts=job.attempts
        )


async def _retry_stuck_jobs_all_tenants() -> None:
    """Tenant-agnostic on purpose (unlike _tick, which only runs the daily
    discovery/digest for one configured tenant) — job-retry reliability
    isn't a feature of the daily-digest automation, it should apply
    regardless of whether that's even configured."""
    async with async_session_factory() as db:
        result = await db.execute(select(Tenant.id))  # tenants table has no RLS
        tenant_ids = [row[0] for row in result.all()]

    for tenant_id in tenant_ids:
        async with async_session_factory() as db:
            try:
                await _retry_stuck_jobs(db, tenant_id)
            except Exception as exc:  # noqa: BLE001 - one tenant's failure must not skip the rest
                logger.error("scheduler_retry_sweep_failed", tenant_id=str(tenant_id), error=str(exc))


async def _tick(tenant_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)
        segment = _today_segment()
        campaign = await _get_or_create_daily_campaign(db, tenant_id, segment)
        await db.commit()

        await set_tenant_context(db, tenant_id)
        run = await _ensure_todays_run(db, tenant_id, campaign)
        if run is not None:
            await db.commit()
            await set_tenant_context(db, tenant_id)
            job = await get_or_create_job(
                db,
                tenant_id=tenant_id,
                job_type=JobType.DISCOVERY,
                idempotency_key=str(run.id),
                payload={"campaign_run_id": str(run.id)},
            )
            await db.commit()
            get_queue().enqueue(
                "app.modules.jobs.handlers.discovery.run",
                str(job.id),
                str(tenant_id),
                str(run.id),
            )
            logger.info("scheduler_triggered_daily_run", segment=segment, run_id=str(run.id))

        await set_tenant_context(db, tenant_id)
        await _maybe_send_pending_digests(db, tenant_id)


async def main() -> None:
    configure_logging()
    settings = get_settings()
    daily_tenant_id = (
        uuid.UUID(settings.daily_discovery_tenant_id) if settings.daily_discovery_tenant_id else None
    )
    if daily_tenant_id is None:
        print(
            "DAILY_DISCOVERY_TENANT_ID not set — daily discovery/digest is off, "
            "but the stuck-job retry sweep below still runs for every tenant. "
            "See docs/DAILY_DIGEST.md."
        )
    else:
        logger.info("scheduler_started", tenant_id=str(daily_tenant_id))

    while True:
        if daily_tenant_id is not None:
            try:
                await _tick(daily_tenant_id)
            except Exception as exc:  # noqa: BLE001 - one bad tick must not kill the scheduler
                logger.error("scheduler_tick_failed", error=str(exc))

        try:
            await _retry_stuck_jobs_all_tenants()
        except Exception as exc:  # noqa: BLE001 - one bad sweep must not kill the scheduler
            logger.error("scheduler_retry_sweep_failed", error=str(exc))

        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())

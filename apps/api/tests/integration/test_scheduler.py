import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "workers"))

from app.core.db import set_tenant_context
from app.modules.audit.enums import AuditEventType
from app.modules.audit.service import log_event
from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job

from .conftest import ADMIN_DATABASE_URL, requires_live_db, requires_matching_env


class _FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(self, *args) -> None:
        self.calls.append(args)


def test_today_segment_returns_a_valid_rotation_member():
    import scheduler

    assert scheduler._today_segment() in scheduler._SEGMENTS_ROTATION


@requires_live_db
@pytest.mark.asyncio
async def test_get_or_create_daily_campaign_is_idempotent(app_session_factory):
    import scheduler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scheduler Campaign Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            campaign_a = await scheduler._get_or_create_daily_campaign(
                session, tenant_id, "restaurants"
            )
            await session.commit()
            first_id = campaign_a.id
            assert campaign_a.status == CampaignStatus.ACTIVE
            assert campaign_a.cities == [scheduler.NATIONWIDE_CITY_SENTINEL]

            await set_tenant_context(session, tenant_id)
            campaign_b = await scheduler._get_or_create_daily_campaign(
                session, tenant_id, "restaurants"
            )
            await session.commit()
            assert campaign_b.id == first_id  # reused, not duplicated
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_ensure_todays_run_does_not_double_trigger(app_session_factory):
    import scheduler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scheduler Run Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            campaign = await scheduler._get_or_create_daily_campaign(
                session, tenant_id, "clinics"
            )
            await session.commit()

            await set_tenant_context(session, tenant_id)
            first_run = await scheduler._ensure_todays_run(session, tenant_id, campaign)
            await session.commit()
            assert first_run is not None

            await set_tenant_context(session, tenant_id)
            second_run = await scheduler._ensure_todays_run(session, tenant_id, campaign)
            assert second_run is None  # already ran today — no double trigger
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_digest_already_sent_tracks_via_audit_log(app_session_factory, two_tenants):
    import scheduler

    tenant_a, _ = two_tenants
    run_id = uuid.uuid4()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await scheduler._digest_already_sent(session, tenant_a.id, run_id) is False

        await log_event(
            session,
            tenant_a.id,
            AuditEventType.DAILY_DIGEST_SENT,
            {"campaign_run_id": str(run_id), "companies": 3},
        )
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        assert await scheduler._digest_already_sent(session, tenant_a.id, run_id) is True


@requires_live_db
@pytest.mark.asyncio
async def test_site_diagnostic_already_sent_tracks_independently_of_the_other_digest(
    app_session_factory, two_tenants
):
    """The two emails are tracked by separate audit events on purpose — one
    failing to send must never block or duplicate the other."""
    import scheduler

    tenant_a, _ = two_tenants
    run_id = uuid.uuid4()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        assert await scheduler._site_diagnostic_already_sent(session, tenant_a.id, run_id) is False

        await log_event(
            session,
            tenant_a.id,
            AuditEventType.DAILY_DIGEST_SENT,
            {"campaign_run_id": str(run_id), "companies": 3},
        )
        await session.commit()

        # The business digest was sent, but the site diagnostic wasn't —
        # they must not be conflated.
        await set_tenant_context(session, tenant_a.id)
        assert await scheduler._site_diagnostic_already_sent(session, tenant_a.id, run_id) is False

        await log_event(
            session,
            tenant_a.id,
            AuditEventType.DAILY_SITE_DIAGNOSTIC_SENT,
            {"campaign_run_id": str(run_id), "companies": 3},
        )
        await session.commit()

        await set_tenant_context(session, tenant_a.id)
        assert await scheduler._site_diagnostic_already_sent(session, tenant_a.id, run_id) is True


@requires_live_db
@pytest.mark.asyncio
async def test_maybe_send_pending_digests_sends_once_and_marks_sent(
    app_session_factory, monkeypatch
):
    import scheduler

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Scheduler Digest Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    sent_emails = []

    def _fake_send_email(smtp_user, smtp_app_password, to_address, subject, text_body, html_body=None):
        sent_emails.append({"to": to_address, "subject": subject})

    monkeypatch.setattr(scheduler, "send_email", _fake_send_email)
    monkeypatch.setattr(scheduler.get_settings(), "gmail_smtp_user", "sender@test.com")
    monkeypatch.setattr(scheduler.get_settings(), "gmail_smtp_app_password", "fake-app-password")
    monkeypatch.setattr(scheduler.get_settings(), "daily_digest_recipient_email", "recipient@test.com")

    try:
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            campaign = Campaign(
                tenant_id=tenant_id,
                name=f"{scheduler._CAMPAIGN_NAME_PREFIX} - restaurants",
                segment="restaurants",
                cities=[scheduler.NATIONWIDE_CITY_SENTINEL],
                state="BR",
                country="BR",
                target_quantity=5,
                status=CampaignStatus.ACTIVE,
            )
            session.add(campaign)
            await session.flush()

            long_ago = datetime.now(UTC) - timedelta(hours=2)
            run = CampaignRun(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                status=CampaignRunStatus.COMPLETED,
                started_at=long_ago,
                finished_at=long_ago,
                companies_found=1,
            )
            session.add(run)
            await session.flush()

            company = Company(
                tenant_id=tenant_id,
                name="Restaurante Digest Teste",
                normalized_name="restaurante digest teste",
                segment="restaurants",
                city="Sorocaba",
                state="SP",
                country="BR",
                status=CompanyStatus.DISCOVERED,
                campaign_run_id=run.id,
            )
            session.add(company)
            await session.commit()

            await set_tenant_context(session, tenant_id)
            await scheduler._maybe_send_pending_digests(session, tenant_id)

            # Two independent emails per pending run now: the business
            # summary digest and the site-diagnostics digest.
            assert len(sent_emails) == 2
            assert all(e["to"] == "recipient@test.com" for e in sent_emails)
            subjects = " ".join(e["subject"] for e in sent_emails)
            assert "diagnóstico de sites" in subjects

            # Second call must not send again — idempotent via audit_log.
            await set_tenant_context(session, tenant_id)
            await scheduler._maybe_send_pending_digests(session, tenant_id)
            assert len(sent_emails) == 2
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_maybe_send_pending_digests_skips_when_email_not_configured(
    app_session_factory, monkeypatch, two_tenants
):
    import scheduler

    tenant_a, _ = two_tenants

    calls = []
    monkeypatch.setattr(scheduler, "send_email", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(scheduler.get_settings(), "gmail_smtp_user", None)

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        await scheduler._maybe_send_pending_digests(session, tenant_a.id)
        assert calls == []


@requires_live_db
@pytest.mark.asyncio
async def test_retry_stuck_jobs_reenqueues_a_retrying_job(
    app_session_factory, monkeypatch, two_tenants
):
    """The actual fix: a job the handler marked RETRYING must get a real
    second attempt, not sit there forever (see _RETRYABLE_JOB_HANDLERS)."""
    import scheduler

    fake_queue = _FakeQueue()
    monkeypatch.setattr(scheduler, "get_queue", lambda: fake_queue)

    tenant_a, _ = two_tenants
    company_id = uuid.uuid4()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.SCORING,
            status=JobStatus.RETRYING,
            idempotency_key=str(company_id),
            payload={"company_id": str(company_id)},
            error="Output failed schema validation: ...",
            attempts=1,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

        await set_tenant_context(session, tenant_a.id)
        await scheduler._retry_stuck_jobs(session, tenant_a.id)

        await set_tenant_context(session, tenant_a.id)
        refreshed = await session.get(Job, job_id)
        assert refreshed.status == JobStatus.PENDING
        assert refreshed.error is None

    assert len(fake_queue.calls) == 1
    assert fake_queue.calls[0] == (
        "app.modules.jobs.handlers.scoring.run",
        str(job_id),
        str(tenant_a.id),
        str(company_id),
    )


@requires_live_db
@pytest.mark.asyncio
async def test_retry_stuck_jobs_gives_up_after_max_attempts(
    app_session_factory, monkeypatch, two_tenants
):
    """Past the cap, a job becomes terminal FAILED — never silent limbo."""
    import scheduler

    fake_queue = _FakeQueue()
    monkeypatch.setattr(scheduler, "get_queue", lambda: fake_queue)

    tenant_a, _ = two_tenants
    company_id = uuid.uuid4()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.BUSINESS_ANALYSIS,
            status=JobStatus.RETRYING,
            idempotency_key=str(company_id),
            payload={"company_id": str(company_id)},
            error="Output failed schema validation: ...",
            attempts=scheduler._MAX_JOB_ATTEMPTS,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

        await set_tenant_context(session, tenant_a.id)
        await scheduler._retry_stuck_jobs(session, tenant_a.id)

        await set_tenant_context(session, tenant_a.id)
        refreshed = await session.get(Job, job_id)
        assert refreshed.status == JobStatus.FAILED

    assert fake_queue.calls == []  # never retried past the cap


@requires_live_db
@pytest.mark.asyncio
async def test_retry_stuck_jobs_skips_job_type_with_no_handler_mapping(
    app_session_factory, monkeypatch, two_tenants
):
    """PING (and anything else not in _RETRYABLE_JOB_HANDLERS) is left
    alone rather than crashing the sweep."""
    import scheduler

    fake_queue = _FakeQueue()
    monkeypatch.setattr(scheduler, "get_queue", lambda: fake_queue)

    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.PING,
            status=JobStatus.RETRYING,
            idempotency_key="ping-test",
            payload={},
            attempts=1,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

        await set_tenant_context(session, tenant_a.id)
        await scheduler._retry_stuck_jobs(session, tenant_a.id)

        await set_tenant_context(session, tenant_a.id)
        refreshed = await session.get(Job, job_id)
        assert refreshed.status == JobStatus.RETRYING  # untouched, not crashed

    assert fake_queue.calls == []


@requires_live_db
@pytest.mark.asyncio
async def test_retry_stuck_jobs_skips_job_missing_expected_payload_key(
    app_session_factory, monkeypatch, two_tenants
):
    import scheduler

    fake_queue = _FakeQueue()
    monkeypatch.setattr(scheduler, "get_queue", lambda: fake_queue)

    tenant_a, _ = two_tenants

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        job = Job(
            tenant_id=tenant_a.id,
            type=JobType.SCORING,
            status=JobStatus.RETRYING,
            idempotency_key="missing-payload-test",
            payload={},  # missing "company_id"
            attempts=1,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

        await set_tenant_context(session, tenant_a.id)
        await scheduler._retry_stuck_jobs(session, tenant_a.id)

        await set_tenant_context(session, tenant_a.id)
        refreshed = await session.get(Job, job_id)
        assert refreshed.status == JobStatus.RETRYING  # left alone, not crashed

    assert fake_queue.calls == []


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_retry_stuck_jobs_all_tenants_covers_every_tenant(
    app_session_factory, monkeypatch, two_tenants
):
    """Deliberately not scoped to DAILY_DISCOVERY_TENANT_ID — job-retry
    reliability applies to every tenant, not just the one configured for
    the daily digest automation."""
    import scheduler

    fake_queue = _FakeQueue()
    monkeypatch.setattr(scheduler, "get_queue", lambda: fake_queue)

    tenant_a, tenant_b = two_tenants
    company_a, company_b = uuid.uuid4(), uuid.uuid4()

    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_a.id)
        session.add(
            Job(
                tenant_id=tenant_a.id,
                type=JobType.SCORING,
                status=JobStatus.RETRYING,
                idempotency_key=str(company_a),
                payload={"company_id": str(company_a)},
                attempts=1,
            )
        )
        await session.commit()

        await set_tenant_context(session, tenant_b.id)
        session.add(
            Job(
                tenant_id=tenant_b.id,
                type=JobType.SCORING,
                status=JobStatus.RETRYING,
                idempotency_key=str(company_b),
                payload={"company_id": str(company_b)},
                attempts=1,
            )
        )
        await session.commit()

    await scheduler._retry_stuck_jobs_all_tenants()

    retried_company_ids = {call[3] for call in fake_queue.calls}
    assert str(company_a) in retried_company_ids
    assert str(company_b) in retried_company_ids

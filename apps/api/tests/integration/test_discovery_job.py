import uuid

import pytest
from sqlalchemy import select

from app.core.db import set_tenant_context
from app.modules.campaigns.enums import CampaignRunStatus, CampaignStatus
from app.modules.campaigns.models import Campaign, CampaignRun
from app.modules.companies.enums import CompanyStatus
from app.modules.companies.models import Company
from app.modules.companies.service import NormalizedRawCompany
from app.modules.jobs.enums import JobStatus, JobType
from app.modules.jobs.models import Job

from .conftest import requires_live_db


class _FakeProvider:
    """Stands in for OverpassProvider/ApifyProvider — tests never hit either
    real API (avoids flakiness/rate limits/cost in CI). Real-world interop
    for both is verified separately, once, by hand — see docs/DISCOVERY.md."""

    def __init__(
        self,
        results_by_city: dict[str, list[NormalizedRawCompany]] | None = None,
        name: str = "fake",
        error: Exception | None = None,
    ) -> None:
        self._results_by_city = results_by_city or {}
        self.name = name
        self._error = error

    async def search(
        self, segment: str, city: str, state: str, country: str, limit: int
    ) -> list[NormalizedRawCompany]:
        if self._error is not None:
            raise self._error
        return self._results_by_city.get(city, [])[:limit]


async def _seed_campaign_run(
    app_session_factory, tenant_id: uuid.UUID, cities: list[str], target_quantity: int
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with app_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        campaign = Campaign(
            tenant_id=tenant_id,
            name="Test Discovery Campaign",
            segment="restaurants",
            cities=cities,
            state="SP",
            country="BR",
            target_quantity=target_quantity,
            status=CampaignStatus.ACTIVE,
        )
        session.add(campaign)
        await session.flush()

        run = CampaignRun(
            tenant_id=tenant_id, campaign_id=campaign.id, status=CampaignRunStatus.PENDING
        )
        session.add(run)
        await session.flush()

        job = Job(
            tenant_id=tenant_id,
            type=JobType.DISCOVERY,
            status=JobStatus.PENDING,
            idempotency_key=str(run.id),
        )
        session.add(job)
        await session.commit()
        return campaign.id, run.id, job.id


def _raw(name: str, external_id: str, **overrides) -> NormalizedRawCompany:
    defaults = dict(
        provider="overpass",
        external_id=external_id,
        name=name,
        segment="restaurants",
        city="Sorocaba",
        state="SP",
        country="BR",
        address="Rua Teste 100",
        phone=None,
    )
    defaults.update(overrides)
    return NormalizedRawCompany(**defaults)


@requires_live_db
@pytest.mark.asyncio
async def test_discovery_job_creates_companies_and_completes_run(
    app_session_factory, monkeypatch
):
    import app.modules.jobs.handlers.discovery as discovery_handler

    tenant_id = uuid.uuid4()

    # This test manages its own tenant (rather than the shared two_tenants
    # fixture) so its admin-only setup/cleanup stays local to the test, next
    # to the job invocation it's supporting.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Discovery Test Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=2
        )

        fake_results = {
            "Sorocaba": [
                _raw("Restaurante A", "node/1"),
                _raw("Restaurante B", "node/2"),
            ]
        }
        monkeypatch.setattr(
            discovery_handler, "OverpassProvider", lambda: _FakeProvider(fake_results)
        )

        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            updated_run = await session.get(CampaignRun, run_id)
            assert updated_run.status == CampaignRunStatus.COMPLETED
            assert updated_run.companies_found == 2
            assert updated_run.companies_validated == 2
            assert updated_run.duplicates == 0
            assert updated_run.enriched == 2

            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert {c.name for c in companies} == {"Restaurante A", "Restaurante B"}

            from app.modules.evidence.models import Evidence

            evidence_result = await session.execute(
                select(Evidence).where(Evidence.tenant_id == tenant_id)
            )
            # Each company gets at least phone + website evidence (present or
            # UNKNOWN) from the inline enrichment step (Fase 3).
            assert len(evidence_result.scalars().all()) >= 4

            updated_job = await session.get(Job, job_id)
            assert updated_job.status == JobStatus.COMPLETED
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_rerunning_discovery_with_same_source_does_not_duplicate_companies(
    app_session_factory, monkeypatch
):
    """Re-processing the same external_id (e.g. a retried/re-enqueued job)
    must attach to the existing company (HIGH confidence via known source),
    not create a second one — spec section 54 idempotency."""
    import app.modules.jobs.handlers.discovery as discovery_handler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Discovery Rerun Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=1
        )
        fake_results = {"Sorocaba": [_raw("Restaurante A", "node/1")]}
        monkeypatch.setattr(
            discovery_handler, "OverpassProvider", lambda: _FakeProvider(fake_results)
        )

        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))
        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert len(companies) == 1

            updated_run = await session.get(CampaignRun, run_id)
            # Second pass: found again, but resolved as a HIGH-confidence
            # duplicate of the same company rather than a new one.
            assert updated_run.duplicates == 1
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_rerunning_discovery_fills_in_phone_found_the_second_time(
    app_session_factory, monkeypatch
):
    """Regression test for a real bug found during the Apify integration
    audit: a HIGH-confidence duplicate match only ever recorded the new
    CompanySource and left the existing Company's phone/website untouched —
    a later run (or a second provider) that actually had the phone number
    never got it onto the canonical record. See
    companies/service.py:merge_missing_fields."""
    import app.modules.jobs.handlers.discovery as discovery_handler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Discovery Merge Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=1
        )

        # First pass: no phone. Second pass: same external_id (same real
        # place), this time with a phone — simulates a re-run finding more
        # data, or (once implemented) a second provider like Apify.
        monkeypatch.setattr(
            discovery_handler,
            "OverpassProvider",
            lambda: _FakeProvider({"Sorocaba": [_raw("Restaurante A", "node/1", phone=None)]}),
        )
        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        monkeypatch.setattr(
            discovery_handler,
            "OverpassProvider",
            lambda: _FakeProvider(
                {"Sorocaba": [_raw("Restaurante A", "node/1", phone="15999998888")]}
            ),
        )
        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert len(companies) == 1
            assert companies[0].phone == "15999998888"
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


async def _run_multi_provider_test(
    app_session_factory,
    monkeypatch,
    tenant_name_prefix: str,
    osm_provider,
    apify_provider,
    test_body,
) -> None:
    """Shared setup for the OSM+Apify tests below: seeds a tenant+campaign,
    wires both provider fakes in (Apify only participates when
    settings.apify_api_token is set, same as production — see
    discovery.py:build_providers), runs discovery once, hands the seeded ids
    to `test_body` for assertions, then cleans up."""
    import app.modules.jobs.handlers.discovery as discovery_handler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"{tenant_name_prefix} {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=5
        )

        monkeypatch.setattr(discovery_handler, "OverpassProvider", lambda: osm_provider)
        monkeypatch.setattr(
            discovery_handler, "ApifyProvider", lambda api_token, actor_id: apify_provider
        )
        monkeypatch.setattr(discovery_handler.get_settings(), "apify_api_token", "fake-token-for-test")

        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        await test_body(app_session_factory, tenant_id, run_id)
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_discovery_runs_both_providers_and_consolidates_results(
    app_session_factory, monkeypatch
):
    osm = _FakeProvider({"Sorocaba": [_raw("Restaurante OSM", "node/1")]}, name="overpass")
    apify = _FakeProvider(
        {"Sorocaba": [_raw("Restaurante Apify", "place/2", provider="apify")]}, name="apify"
    )

    async def check(app_session_factory, tenant_id, run_id):
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert {c.name for c in companies} == {"Restaurante OSM", "Restaurante Apify"}

            run = await session.get(CampaignRun, run_id)
            assert run.status == CampaignRunStatus.COMPLETED
            assert run.companies_found == 2

    await _run_multi_provider_test(
        app_session_factory, monkeypatch, "Multi Provider Tenant", osm, apify, check
    )


@requires_live_db
@pytest.mark.asyncio
async def test_apify_failure_does_not_block_overpass_results(app_session_factory, monkeypatch):
    from app.modules.discovery.base import DiscoveryProviderError

    osm = _FakeProvider({"Sorocaba": [_raw("Restaurante OSM", "node/1")]}, name="overpass")
    apify = _FakeProvider(name="apify", error=DiscoveryProviderError("Apify down"))

    async def check(app_session_factory, tenant_id, run_id):
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert {c.name for c in companies} == {"Restaurante OSM"}

            run = await session.get(CampaignRun, run_id)
            assert run.status == CampaignRunStatus.COMPLETED  # one provider failing != run failing
            assert any(e.get("provider") == "apify" for e in run.errors)

    await _run_multi_provider_test(
        app_session_factory, monkeypatch, "Apify Down Tenant", osm, apify, check
    )


@requires_live_db
@pytest.mark.asyncio
async def test_overpass_failure_does_not_block_apify_results(app_session_factory, monkeypatch):
    from app.modules.discovery.base import DiscoveryProviderError

    osm = _FakeProvider(name="overpass", error=DiscoveryProviderError("Overpass down"))
    apify = _FakeProvider(
        {"Sorocaba": [_raw("Restaurante Apify", "place/1", provider="apify")]}, name="apify"
    )

    async def check(app_session_factory, tenant_id, run_id):
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert {c.name for c in companies} == {"Restaurante Apify"}

            run = await session.get(CampaignRun, run_id)
            assert run.status == CampaignRunStatus.COMPLETED
            assert any(e.get("provider") == "overpass" for e in run.errors)

    await _run_multi_provider_test(
        app_session_factory, monkeypatch, "Overpass Down Tenant", osm, apify, check
    )


@requires_live_db
@pytest.mark.asyncio
async def test_cross_provider_duplicate_is_merged_via_matching_domain(
    app_session_factory, monkeypatch
):
    """OSM and Apify finding the "same" real place under slightly different
    names must not create two companies — matched here via domain (spec
    section 10's OSM x Apify case), and the phone Apify has but OSM doesn't
    must land on the single resulting company (spec section 11 merge)."""
    osm = _FakeProvider(
        {
            "Sorocaba": [
                _raw(
                    "Hamburgueria Rock",
                    "node/1",
                    website="https://rockburger.com.br",
                    phone=None,
                )
            ]
        },
        name="overpass",
    )
    apify = _FakeProvider(
        {
            "Sorocaba": [
                _raw(
                    "Rock Hamburgueria",
                    "place/1",
                    provider="apify",
                    website="https://www.rockburger.com.br/cardapio",
                    phone="15988887777",
                )
            ]
        },
        name="apify",
    )

    async def check(app_session_factory, tenant_id, run_id):
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert len(companies) == 1  # not 2 — resolved as the same company
            assert companies[0].phone == "15988887777"  # merged in from Apify

            run = await session.get(CampaignRun, run_id)
            assert run.duplicates == 1

    await _run_multi_provider_test(
        app_session_factory, monkeypatch, "Cross Provider Dedup Tenant", osm, apify, check
    )


@requires_live_db
@pytest.mark.asyncio
async def test_apify_not_configured_runs_osm_only(app_session_factory, monkeypatch):
    """No token set (settings.apify_api_token is None) must not error — the
    system degrades to OSM-only, exactly like the AI Gateway does when
    anthropic_api_key is unset."""
    import app.modules.jobs.handlers.discovery as discovery_handler

    tenant_id = uuid.uuid4()
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Apify Unconfigured Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=5
        )

        monkeypatch.setattr(
            discovery_handler,
            "OverpassProvider",
            lambda: _FakeProvider({"Sorocaba": [_raw("Restaurante OSM", "node/1")]}, name="overpass"),
        )
        monkeypatch.setattr(discovery_handler.get_settings(), "apify_api_token", None)

        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            companies = result.scalars().all()
            assert {c.name for c in companies} == {"Restaurante OSM"}

            run = await session.get(CampaignRun, run_id)
            assert run.status == CampaignRunStatus.COMPLETED
            assert run.errors == []
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()


@requires_live_db
@pytest.mark.asyncio
async def test_apify_permanently_closed_place_is_discovered_as_invalid(
    app_session_factory, monkeypatch
):
    """Real signal Apify's Google Maps data provides that OSM never had —
    a place reported permanently closed shouldn't even need a human to mark
    it inactive (spec section 15's original ask)."""
    osm = _FakeProvider(name="overpass")
    apify = _FakeProvider(
        {
            "Sorocaba": [
                _raw(
                    "Restaurante Fechado",
                    "place/1",
                    provider="apify",
                    permanently_closed=True,
                )
            ]
        },
        name="apify",
    )

    async def check(app_session_factory, tenant_id, run_id):
        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            [company] = result.scalars().all()
            assert company.status == CompanyStatus.INVALID

    await _run_multi_provider_test(
        app_session_factory, monkeypatch, "Permanently Closed Tenant", osm, apify, check
    )


@requires_live_db
@pytest.mark.asyncio
async def test_new_companies_are_stamped_with_the_run_that_discovered_them(
    app_session_factory, monkeypatch
):
    """Needed for the daily digest (workers/scheduler.py) to know exactly
    which companies a given run introduced — set once at creation, never on
    a later merge, so a re-match doesn't get re-reported as new."""
    import app.modules.jobs.handlers.discovery as discovery_handler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from .conftest import ADMIN_DATABASE_URL

    tenant_id = uuid.uuid4()
    admin_engine = create_async_engine(ADMIN_DATABASE_URL)
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)

    from app.modules.tenancy.models import Tenant

    async with admin_factory() as admin_db:
        tenant = Tenant(id=tenant_id, name=f"Run Stamp Tenant {uuid.uuid4().hex[:6]}")
        admin_db.add(tenant)
        await admin_db.commit()

    try:
        campaign_id, run_id, job_id = await _seed_campaign_run(
            app_session_factory, tenant_id, ["Sorocaba"], target_quantity=1
        )
        monkeypatch.setattr(
            discovery_handler,
            "OverpassProvider",
            lambda: _FakeProvider({"Sorocaba": [_raw("Restaurante A", "node/1")]}),
        )
        await discovery_handler._run(str(job_id), str(tenant_id), str(run_id))

        async with app_session_factory() as session:
            await set_tenant_context(session, tenant_id)
            result = await session.execute(select(Company).where(Company.tenant_id == tenant_id))
            [company] = result.scalars().all()
            assert company.campaign_run_id == run_id
    finally:
        async with admin_factory() as admin_db:
            tenant = await admin_db.get(Tenant, tenant_id)
            if tenant is not None:
                await admin_db.delete(tenant)
                await admin_db.commit()
        await admin_engine.dispose()

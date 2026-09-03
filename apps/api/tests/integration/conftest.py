import os
import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._jwt_helpers import generate_es256_keypair, sign_token

# Two separate connections on purpose:
#  - TEST_ADMIN_DATABASE_URL: the Supabase/Postgres owner role. Bypasses RLS —
#    used only to seed/tear down fixture data (tenants, users, memberships),
#    mirroring what the real migrations role can do that the app role can't.
#  - TEST_DATABASE_URL: the restricted `ai_sales_os_app` role from migration
#    0001. This is the connection whose RLS behavior we're actually testing —
#    it must match what app.core.config.Settings.database_url points to in a
#    real deployment.
ADMIN_DATABASE_URL = os.environ.get("TEST_ADMIN_DATABASE_URL")
APP_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

requires_live_db = pytest.mark.skipif(
    not (ADMIN_DATABASE_URL and APP_DATABASE_URL),
    reason=(
        "Integration tests need TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL "
        "(the ai_sales_os_app role connection string) pointed at a real "
        "Postgres/Supabase test database with migration 0001 already applied. "
        "See docs/DATABASE.md."
    ),
)

# app.main.app's DB engine is built once at import time from the DATABASE_URL
# env var (see app.core.db). For an HTTP-level test to exercise the real
# RLS-restricted app role — not whatever DATABASE_URL happened to be set to
# when the test process started — DATABASE_URL must be exported equal to
# TEST_DATABASE_URL beforehand. See docs/DATABASE.md.
requires_matching_env = pytest.mark.skipif(
    os.environ.get("DATABASE_URL") != APP_DATABASE_URL,
    reason="DATABASE_URL must be exported equal to TEST_DATABASE_URL for HTTP-level tests.",
)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_engine():
    """app.core.db.engine is a module-level singleton, shared by every test
    that imports app.main.app (auth/campaigns HTTP-level tests). pytest-asyncio
    gives each test function its own event loop by default, but pooled asyncpg
    connections are bound to the loop they were opened in — reusing one across
    a loop boundary blows up with "Event loop is closed" well after the fact,
    in whatever test happens to run next. Disposing the pool after every test
    (while its loop is still alive) prevents that from leaking into the next
    test's loop.
    """
    yield
    from app.core.db import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def admin_session():
    engine = create_async_engine(ADMIN_DATABASE_URL) if ADMIN_DATABASE_URL else None
    if engine is None:
        yield None
        return
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def app_session_factory():
    if not APP_DATABASE_URL:
        yield None
        return
    engine = create_async_engine(APP_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(admin_session):
    from app.modules.tenancy.models import Tenant

    tenant_a = Tenant(id=uuid.uuid4(), name=f"Test Tenant A {uuid.uuid4().hex[:6]}")
    tenant_b = Tenant(id=uuid.uuid4(), name=f"Test Tenant B {uuid.uuid4().hex[:6]}")
    admin_session.add_all([tenant_a, tenant_b])
    await admin_session.commit()

    yield tenant_a, tenant_b

    await admin_session.delete(tenant_a)
    await admin_session.delete(tenant_b)
    await admin_session.commit()


@pytest_asyncio.fixture
async def stub_jwks(monkeypatch):
    """Points app.modules.auth.jwks at a locally-generated key instead of a real
    network call — see tests/_jwt_helpers.py for why (ES256, matching what
    Supabase actually issues). Returns (private_pem, kid) for signing tokens."""
    import app.modules.auth.jwks as jwks_module

    kid = f"test-kid-{uuid.uuid4().hex[:8]}"
    private_pem, jwk_dict = generate_es256_keypair(kid)

    monkeypatch.setitem(jwks_module._cache, "keys_by_kid", {kid: jwk_dict})
    monkeypatch.setitem(jwks_module._cache, "fetched_at", time.monotonic())

    async def _fake_fetch():
        return {kid: jwk_dict}

    monkeypatch.setattr(jwks_module, "_fetch_jwks", _fake_fetch)
    return private_pem, kid


@pytest_asyncio.fixture
async def authenticated_client(admin_session, stub_jwks):
    """Factory fixture: `token = await make_token(tenant_id, role)` provisions a
    real `users` row + `memberships` row (via the admin/bypass-RLS connection,
    same as a real onboarding flow would) and returns a bearer token for it.
    Cleans up everything it created afterward."""
    from app.modules.auth.models import User
    from app.modules.tenancy.models import Membership

    private_pem, kid = stub_jwks
    created_users: list[User] = []

    async def _make_token(tenant_id: uuid.UUID, role) -> str:
        auth_user_id = uuid.uuid4()
        email = f"{uuid.uuid4().hex}@test.com"
        user = User(auth_user_id=auth_user_id, email=email)
        admin_session.add(user)
        await admin_session.flush()

        membership = Membership(user_id=user.id, tenant_id=tenant_id, role=role)
        admin_session.add(membership)
        await admin_session.commit()

        created_users.append(user)

        return sign_token(
            {"sub": str(auth_user_id), "email": email, "aud": "authenticated"}, private_pem, kid
        )

    yield _make_token

    # Deleting the user is enough: `memberships.user_id` has ON DELETE CASCADE
    # (as does `.tenant_id`, which is why this fixture doesn't need to race
    # `two_tenants`' teardown either — whichever runs first, the membership
    # row ends up gone).
    for user in created_users:
        await admin_session.delete(user)
    await admin_session.commit()

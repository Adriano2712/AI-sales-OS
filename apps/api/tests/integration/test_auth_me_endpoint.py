import uuid

import httpx
import pytest

from tests._jwt_helpers import sign_token

from .conftest import requires_live_db, requires_matching_env


@requires_live_db
@requires_matching_env
@pytest.mark.asyncio
async def test_me_endpoint_resolves_tenant_and_provisions_user(
    admin_session, two_tenants, stub_jwks
):
    """Full round-trip: JWT in -> local user auto-provisioned -> membership
    resolved -> RLS-scoped tenant context returned. Exercises the whole Phase 0
    auth/tenancy stack through the actual HTTP layer, not just unit-level pieces.

    Deliberately doesn't use the `authenticated_client` fixture: this test's
    whole point is the *before-membership-exists* 403 case, which that fixture
    (by design) always skips past.
    """
    from app.main import app
    from app.modules.tenancy.enums import Role
    from app.modules.tenancy.models import Membership

    private_pem, kid = stub_jwks
    tenant_a, _ = two_tenants
    auth_user_id = uuid.uuid4()
    email = f"{uuid.uuid4().hex}@test.com"
    token = sign_token(
        {"sub": str(auth_user_id), "email": email, "aud": "authenticated"}, private_pem, kid
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # First call auto-provisions the `users` row but has no membership yet.
        first = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert first.status_code == 403

        from sqlalchemy import select

        from app.modules.auth.models import User

        result = await admin_session.execute(select(User).where(User.auth_user_id == auth_user_id))
        user = result.scalar_one()

        membership = Membership(user_id=user.id, tenant_id=tenant_a.id, role=Role.MANAGER)
        admin_session.add(membership)
        await admin_session.commit()

        second = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert second.status_code == 200
        body = second.json()
        assert body["tenant_id"] == str(tenant_a.id)
        assert body["role"] == "MANAGER"

        # Deleting the user is enough: memberships.user_id (and .tenant_id) both
        # have ON DELETE CASCADE, so an explicit membership delete here would
        # just race two_tenants' teardown for nothing.
        await admin_session.delete(user)
        await admin_session.commit()

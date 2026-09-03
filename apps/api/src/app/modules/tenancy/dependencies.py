import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, set_tenant_context, set_user_context
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.auth.service import get_or_create_user
from app.modules.tenancy.enums import Role, WRITE_ROLES
from app.modules.tenancy.models import Membership
from app.modules.tenancy.schemas import TenantContext


async def get_tenant_context(
    x_tenant_id: uuid.UUID | None = Header(default=None),
    authenticated: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    user = await get_or_create_user(db, authenticated)
    # Commit here, before any of the checks below that can raise: a first-time
    # login with no membership yet must still persist the auto-provisioned user
    # row, not roll it back along with the 403. See auth/service.py.
    await db.commit()

    await set_user_context(db, user.id)

    memberships_result = await db.execute(select(Membership).where(Membership.user_id == user.id))
    memberships = list(memberships_result.scalars())

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant membership",
        )

    if x_tenant_id is not None:
        membership = next((m for m in memberships if m.tenant_id == x_tenant_id), None)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a member of the requested tenant",
            )
    elif len(memberships) == 1:
        membership = memberships[0]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple tenant memberships found; specify X-Tenant-Id header",
        )

    await db.commit()
    return TenantContext(user_id=user.id, tenant_id=membership.tenant_id, role=membership.role)


async def get_tenant_db(
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSession, None]:
    """Session with the Postgres RLS session variable set for this request's tenant.

    NOTE: get_db and get_tenant_context each open their own session via FastAPI's
    dependency cache (same request -> same instance), so this reuses that instance
    rather than opening a third connection.
    """
    await set_tenant_context(db, context.tenant_id)
    yield db


def require_role(*allowed: Role):
    async def _check(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if context.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {context.role} is not permitted to perform this action",
            )
        return context

    return _check


def require_write_access():
    return require_role(*WRITE_ROLES)

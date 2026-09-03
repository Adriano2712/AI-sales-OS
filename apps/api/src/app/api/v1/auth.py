from fastapi import APIRouter, Depends

from app.modules.tenancy.dependencies import get_tenant_context
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=TenantContext)
async def me(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """Returns the authenticated user's resolved tenant + role. Used by the frontend
    to confirm the session is valid and by integration tests to verify JWT + RLS
    wiring end-to-end."""
    return context

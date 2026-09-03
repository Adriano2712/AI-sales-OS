from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.schemas import DashboardSummary
from app.modules.dashboard.service import get_summary
from app.modules.tenancy.dependencies import get_tenant_context, get_tenant_db
from app.modules.tenancy.schemas import TenantContext

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary_endpoint(
    context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_tenant_db),
) -> DashboardSummary:
    return await get_summary(db, context.tenant_id)

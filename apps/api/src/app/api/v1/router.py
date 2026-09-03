from fastapi import APIRouter

from app.api.v1 import auth, campaigns, companies, dashboard, health, jobs, messages, opportunities

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(jobs.router)
router.include_router(campaigns.router)
router.include_router(companies.router)
router.include_router(opportunities.router)
router.include_router(dashboard.router)
router.include_router(messages.router)

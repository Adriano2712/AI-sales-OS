import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse
from app.modules.ai_gateway.models import AICall
from app.modules.ai_gateway.router import get_fallback_provider_for_task, get_provider_for_task

logger = get_logger(module="ai_gateway")


async def run_ai_task(
    db: AsyncSession,
    provider: AIProvider,
    tenant_id: uuid.UUID,
    request: AIRequest,
) -> AIResponse:
    """Runs an AI Gateway request and unconditionally logs the outcome to `ai_calls`,
    success or failure, so cost/error visibility never depends on the caller
    remembering to log it."""
    try:
        response = await provider.generate(request)
    except AIProviderError as exc:
        db.add(
            AICall(
                tenant_id=tenant_id,
                task=request.task,
                provider=provider.name,
                model=request.model or "unknown",
                status="error",
                error=str(exc),
            )
        )
        await db.flush()
        raise

    db.add(
        AICall(
            tenant_id=tenant_id,
            task=request.task,
            provider=response.provider,
            model=response.model,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            latency_ms=response.latency_ms,
            estimated_cost_usd=response.estimated_cost_usd,
            status="success",
        )
    )
    await db.flush()
    return response


async def run_ai_task_routed(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request: AIRequest,
) -> AIResponse:
    """Preferred entrypoint for job handlers (spec section 17): resolves the
    provider for `request.task` via the Model Router instead of the caller
    constructing one directly, and falls back to a second provider only when
    that task has explicitly opted in (TASK_FALLBACK in router.py — empty by
    default, spec section 19: never fall back for an incompatible task).
    Both the primary and the fallback attempt are logged to `ai_calls`, so a
    fallback is visible in cost/observability data, not hidden."""
    primary = get_provider_for_task(request.task)
    try:
        return await run_ai_task(db, primary, tenant_id, request)
    except AIProviderError as primary_exc:
        fallback = get_fallback_provider_for_task(request.task)
        if fallback is None:
            raise
        logger.error(
            "ai_gateway_falling_back",
            task=request.task,
            primary_provider=primary.name,
            fallback_provider=fallback.name,
            error=str(primary_exc),
        )
        return await run_ai_task(db, fallback, tenant_id, request)

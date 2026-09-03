import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse
from app.modules.ai_gateway.models import AICall


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

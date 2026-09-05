import pytest
from pydantic import BaseModel

from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse
from app.modules.ai_gateway.router import TASK_FALLBACK, TASK_PROVIDER
from app.modules.ai_gateway.service import run_ai_task, run_ai_task_routed


class _EchoSchema(BaseModel):
    text: str


class _FakeSession:
    """Stands in for AsyncSession's add/flush — enough for ai_gateway.service,
    without needing a real database connection."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


class _SucceedingProvider(AIProvider):
    name = "fake"

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            output=_EchoSchema(text="hello"),
            raw_text='{"text": "hello"}',
            provider=self.name,
            model="fake-model",
            tokens_input=10,
            tokens_output=5,
            latency_ms=42,
            estimated_cost_usd=0.001,
        )


class _FailingProvider(AIProvider):
    name = "fake"

    async def generate(self, request: AIRequest) -> AIResponse:
        raise AIProviderError("provider exploded")


def _request() -> AIRequest:
    return AIRequest(
        task="unit_test",
        system_prompt="system",
        user_prompt="user",
        output_schema=_EchoSchema,
    )


@pytest.mark.asyncio
async def test_successful_call_logs_ai_call_with_usage():
    db = _FakeSession()
    response = await run_ai_task(db, _SucceedingProvider(), tenant_id="00000000-0000-0000-0000-000000000000", request=_request())  # type: ignore[arg-type]

    assert response.output.text == "hello"
    assert len(db.added) == 1
    logged = db.added[0]
    assert logged.status == "success"
    assert logged.tokens_input == 10
    assert logged.tokens_output == 5
    assert logged.estimated_cost_usd == 0.001


@pytest.mark.asyncio
async def test_failed_call_logs_error_and_reraises():
    db = _FakeSession()

    with pytest.raises(AIProviderError):
        await run_ai_task(db, _FailingProvider(), tenant_id="00000000-0000-0000-0000-000000000000", request=_request())  # type: ignore[arg-type]

    assert len(db.added) == 1
    logged = db.added[0]
    assert logged.status == "error"
    assert "provider exploded" in logged.error


@pytest.mark.asyncio
async def test_routed_call_uses_the_router_and_never_falls_back_when_none_is_configured(
    monkeypatch,
):
    """Fase 2: the common case today — every existing task has no fallback
    configured (spec section 19), so a failure must propagate, not silently
    retry against a different, unvalidated model."""
    import app.modules.ai_gateway.service as ai_gateway_service

    monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", lambda task: _FailingProvider())
    db = _FakeSession()

    with pytest.raises(AIProviderError):
        await run_ai_task_routed(db, tenant_id="00000000-0000-0000-0000-000000000000", request=_request())  # type: ignore[arg-type]

    # Only the one (failed) attempt was logged — no silent second call.
    assert len(db.added) == 1
    assert db.added[0].status == "error"


@pytest.mark.asyncio
async def test_routed_call_falls_back_when_the_task_opts_in(monkeypatch):
    import app.modules.ai_gateway.service as ai_gateway_service

    monkeypatch.setattr(ai_gateway_service, "get_provider_for_task", lambda task: _FailingProvider())
    monkeypatch.setattr(
        ai_gateway_service, "get_fallback_provider_for_task", lambda task: _SucceedingProvider()
    )
    db = _FakeSession()

    response = await run_ai_task_routed(db, tenant_id="00000000-0000-0000-0000-000000000000", request=_request())  # type: ignore[arg-type]

    assert response.output.text == "hello"
    # Both attempts are visible in ai_calls — a fallback is observable, not hidden.
    assert len(db.added) == 2
    assert db.added[0].status == "error"
    assert db.added[1].status == "success"


def test_no_existing_task_has_fallback_configured_by_default():
    """Guards the deliberate Fase 2 scope decision: fallback exists as a
    mechanism, but is off for every task already in production until its
    output quality on the other provider has been validated."""
    for task in TASK_PROVIDER:
        assert task not in TASK_FALLBACK

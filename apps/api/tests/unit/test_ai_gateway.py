import pytest
from pydantic import BaseModel

from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse
from app.modules.ai_gateway.service import run_ai_task


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

import json
import time

import anthropic
from pydantic import BaseModel, ValidationError

from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse

# Per-model USD price per 1M tokens (input, output). Kept close to the call site so
# a price change is a one-line diff, not a hunt through the codebase.
_PRICING_PER_MILLION_TOKENS = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _estimate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    input_price, output_price = _PRICING_PER_MILLION_TOKENS.get(model, (0.0, 0.0))
    return (tokens_input / 1_000_000) * input_price + (tokens_output / 1_000_000) * output_price


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, request: AIRequest) -> AIResponse:
        model = request.model or _DEFAULT_MODEL
        tool_schema = request.output_schema.model_json_schema()
        tool_name = "emit_result"

        started = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=model,
                max_tokens=4096,
                system=request.system_prompt,
                messages=[{"role": "user", "content": request.user_prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": "Emit the structured result for this task.",
                        "input_schema": tool_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except anthropic.APIError as exc:
            raise AIProviderError(str(exc)) from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        tool_use = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise AIProviderError("Model did not return the expected tool_use block")

        try:
            output: BaseModel = request.output_schema.model_validate(tool_use.input)
        except ValidationError as exc:
            raise AIProviderError(f"Output failed schema validation: {exc}") from exc

        tokens_input = message.usage.input_tokens
        tokens_output = message.usage.output_tokens

        return AIResponse(
            output=output,
            raw_text=json.dumps(tool_use.input),
            provider=self.name,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            estimated_cost_usd=_estimate_cost(model, tokens_input, tokens_output),
        )

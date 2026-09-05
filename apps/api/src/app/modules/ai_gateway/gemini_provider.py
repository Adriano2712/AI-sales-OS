import time

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.modules.ai_gateway.base import AIProvider, AIProviderError, AIRequest, AIResponse

# Real pricing per 1M tokens (input, output), USD — fetched directly from
# https://ai.google.dev/gemini-api/docs/pricing on 2026-09-05 (not a
# third-party aggregator: several disagreed with each other on this exact
# question during Fase 2's own research, so only the official page was
# trusted). Gemini 2.5 models — including the cheaper 2.5 Flash-Lite — are
# scheduled for retirement 2026-10-16, so the default here is a current 3.x
# model rather than the soon-dead cheaper option. Re-verify before trusting
# this for real budgeting; ai_calls logs the real token counts either way,
# so a stale price here undercounts/overcounts cost, it never hides usage.
_PRICING_PER_MILLION_TOKENS = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
}
_DEFAULT_MODEL = "gemini-3.1-flash-lite"
"""Cheapest current (non-retiring) model — matches the role spec section 18
gives Gemini: high-volume classification, structured extraction, low-cost
pre-filtering. Not the model for tasks needing Claude-level synthesis."""


def _estimate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    input_price, output_price = _PRICING_PER_MILLION_TOKENS.get(model, (0.0, 0.0))
    return (tokens_input / 1_000_000) * input_price + (tokens_output / 1_000_000) * output_price


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generate(self, request: AIRequest) -> AIResponse:
        model = request.model or _DEFAULT_MODEL

        started = time.monotonic()
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=request.user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=request.system_prompt,
                    response_mime_type="application/json",
                    response_schema=request.output_schema,
                    # High-reliability structured output (Google's own
                    # guidance): reduces variance from the schema shape.
                    temperature=0,
                ),
            )
        except errors.APIError as exc:
            raise AIProviderError(str(exc)) from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        raw_text = response.text
        if raw_text is None:
            raise AIProviderError(
                "Gemini returned no text content — possibly blocked by safety filters"
            )

        # Independently re-validated here rather than trusting the SDK's own
        # response.parsed — same discipline as AnthropicProvider (spec
        # section 37: validated by schema before ever being trusted),
        # applied uniformly regardless of which provider answered.
        try:
            output = request.output_schema.model_validate_json(raw_text)
        except ValidationError as exc:
            raise AIProviderError(f"Output failed schema validation: {exc}") from exc

        usage = response.usage_metadata
        tokens_input = (usage.prompt_token_count or 0) if usage else 0
        # "Thinking" tokens are billed as output by Gemini's own pricing —
        # folded in here so the cost estimate isn't silently short.
        tokens_output = (
            ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        )

        return AIResponse(
            output=output,
            raw_text=raw_text,
            provider=self.name,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            estimated_cost_usd=_estimate_cost(model, tokens_input, tokens_output),
        )

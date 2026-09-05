from app.modules.ai_gateway.anthropic_provider import _estimate_cost
from app.modules.ai_gateway.gemini_provider import _estimate_cost as _estimate_gemini_cost


def test_cost_estimation_known_model():
    cost = _estimate_cost("claude-haiku-4-5-20251001", tokens_input=1_000_000, tokens_output=0)
    assert cost == 0.80


def test_cost_estimation_combines_input_and_output():
    cost = _estimate_cost(
        "claude-sonnet-5", tokens_input=1_000_000, tokens_output=1_000_000
    )
    assert cost == 3.00 + 15.00


def test_cost_estimation_unknown_model_defaults_to_zero():
    cost = _estimate_cost("some-future-model", tokens_input=1_000_000, tokens_output=1_000_000)
    assert cost == 0.0


def test_gemini_cost_estimation_known_model():
    # Real pricing fetched from ai.google.dev/gemini-api/docs/pricing on
    # 2026-09-05 (see gemini_provider.py's own comment on that lookup).
    cost = _estimate_gemini_cost("gemini-3.1-flash-lite", tokens_input=1_000_000, tokens_output=1_000_000)
    assert cost == 0.25 + 1.50


def test_gemini_cost_estimation_unknown_model_defaults_to_zero():
    cost = _estimate_gemini_cost("some-future-gemini-model", tokens_input=1_000_000, tokens_output=1_000_000)
    assert cost == 0.0

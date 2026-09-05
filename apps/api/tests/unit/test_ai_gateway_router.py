import pytest

from app.core.config import get_settings
from app.modules.ai_gateway.anthropic_provider import AnthropicProvider
from app.modules.ai_gateway.gemini_provider import GeminiProvider
from app.modules.ai_gateway.router import (
    ProviderNotConfigured,
    TASK_FALLBACK,
    TASK_PROVIDER,
    get_fallback_provider_for_task,
    get_provider_for_task,
)


@pytest.fixture(autouse=True)
def _configured_keys(monkeypatch):
    """Both keys present by default — individual tests clear one to test the
    "not configured" path. Never real keys (spec section 39)."""
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "fake-anthropic-key")
    monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-gemini-key")


def test_every_existing_task_defaults_to_anthropic():
    """Real finding this guards: adding Gemini must change zero behavior for
    tasks nobody has explicitly moved yet."""
    for task in ("business_analysis", "message_generation", "site_diagnostic"):
        assert TASK_PROVIDER[task] == "anthropic"
        provider = get_provider_for_task(task)
        assert isinstance(provider, AnthropicProvider)


def test_unknown_task_falls_back_to_the_default_provider():
    provider = get_provider_for_task("some_future_task_nobody_configured_yet")
    assert isinstance(provider, AnthropicProvider)


def test_task_routed_to_gemini_returns_gemini_provider(monkeypatch):
    monkeypatch.setitem(TASK_PROVIDER, "a_test_task", "gemini")
    provider = get_provider_for_task("a_test_task")
    assert isinstance(provider, GeminiProvider)


def test_raises_provider_not_configured_when_key_missing(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    with pytest.raises(ProviderNotConfigured):
        get_provider_for_task("business_analysis")


def test_raises_provider_not_configured_for_gemini_when_its_key_missing(monkeypatch):
    monkeypatch.setitem(TASK_PROVIDER, "a_test_task", "gemini")
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    with pytest.raises(ProviderNotConfigured):
        get_provider_for_task("a_test_task")


def test_unknown_provider_name_raises_value_error(monkeypatch):
    monkeypatch.setitem(TASK_PROVIDER, "a_test_task", "not_a_real_provider")
    with pytest.raises(ValueError, match="Unknown AI provider"):
        get_provider_for_task("a_test_task")


def test_fallback_is_none_by_default_for_every_existing_task():
    """Spec section 19: never fall back for a task incompatible with the
    other model — the safe default is no fallback until a task opts in."""
    for task in ("business_analysis", "message_generation", "site_diagnostic"):
        assert task not in TASK_FALLBACK
        assert get_fallback_provider_for_task(task) is None


def test_fallback_returns_the_configured_provider_when_opted_in(monkeypatch):
    monkeypatch.setitem(TASK_FALLBACK, "a_test_task", "gemini")
    fallback = get_fallback_provider_for_task("a_test_task")
    assert isinstance(fallback, GeminiProvider)

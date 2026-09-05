from app.core.config import get_settings
from app.modules.ai_gateway.anthropic_provider import AnthropicProvider
from app.modules.ai_gateway.base import AIProvider
from app.modules.ai_gateway.gemini_provider import GeminiProvider

# Which provider answers each task — the one place this decision lives (spec
# section 17: the rest of the app never calls a model API directly, all of
# it funnels through here via get_provider_for_task). Every existing task
# defaults to "anthropic" so adding Gemini changes zero behavior until a
# task is deliberately moved — model choice per task is spec section 18's
# call to make later (Gemini for high-volume/cheap/classification work,
# Claude for synthesis), not something Fase 2 forces on working code.
TASK_PROVIDER: dict[str, str] = {
    "business_analysis": "anthropic",
    "message_generation": "anthropic",
    "site_diagnostic": "anthropic",
}
_DEFAULT_PROVIDER = "anthropic"

# Per-task fallback opt-in (spec section 19: never fall back for a task
# incompatible with the other model). Empty on purpose today — no existing
# task's output quality has been validated against the other provider yet;
# turning fallback on for a task is a deliberate future choice, not a
# default that comes free with adding a second provider.
TASK_FALLBACK: dict[str, str] = {}

_PROVIDER_BUILDERS = {"anthropic": AnthropicProvider, "gemini": GeminiProvider}


class ProviderNotConfigured(Exception):
    """Raised when a task is routed to a provider whose API key isn't set."""


def get_provider_for_task(task: str) -> AIProvider:
    """The only place in the app that decides *which* AIProvider answers a
    given task. Callers never construct AnthropicProvider/GeminiProvider
    directly — see jobs/handlers/*.py."""
    provider_name = TASK_PROVIDER.get(task, _DEFAULT_PROVIDER)
    return _build_provider(provider_name, task)


def get_fallback_provider_for_task(task: str) -> AIProvider | None:
    """None when no fallback is configured for this task — the common case
    today (see TASK_FALLBACK above)."""
    fallback_name = TASK_FALLBACK.get(task)
    if fallback_name is None:
        return None
    return _build_provider(fallback_name, task)


def _build_provider(provider_name: str, task: str) -> AIProvider:
    settings = get_settings()
    builder = _PROVIDER_BUILDERS.get(provider_name)
    if builder is None:
        raise ValueError(f"Unknown AI provider '{provider_name}' configured for task '{task}'")

    key_attr = "anthropic_api_key" if provider_name == "anthropic" else "gemini_api_key"
    api_key = getattr(settings, key_attr)
    if not api_key:
        raise ProviderNotConfigured(
            f"Task '{task}' is routed to '{provider_name}', but its API key isn't configured"
        )
    return builder(api_key=api_key)

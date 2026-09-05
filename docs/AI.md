# AI Gateway

`apps/api/src/app/modules/ai_gateway/`

## Interface

Domain code never imports a provider SDK directly, and (since Fase 2) never
constructs a provider directly either. Service functions (`analyze_business`,
`generate_message`, `analyze_website`) build an `AIRequest` (task name,
system/user prompt, a Pydantic `output_schema`) and call
`ai_gateway.service.run_ai_task_routed(db, tenant_id, request)`, which:

1. Resolves the provider for `request.task` via the **Model Router**
   (`ai_gateway/router.py::get_provider_for_task`) — the one place that
   decides *which* provider/model answers a task.
2. Calls `provider.generate(request)` through `run_ai_task`, which logs the
   outcome to `ai_calls` unconditionally (success or failure), so cost
   visibility never depends on a caller remembering to log it.
3. On failure, falls back to a second provider **only if that task has
   explicitly opted in** (`router.py::TASK_FALLBACK` — empty by default; spec
   section 19: never fall back for a task incompatible with the other
   model). Both the failed attempt and the fallback attempt are logged.
4. Returns the schema-validated output, or re-raises `AIProviderError`.

Swapping/adding providers means writing a new `AIProvider` implementation
(`ai_gateway/base.py`) and registering it in `router.py`'s
`_PROVIDER_BUILDERS`; nothing outside `ai_gateway/` changes. `run_ai_task`
(taking a provider directly) still exists for callers that already know
their provider — `run_ai_task_routed` is the one job handlers use.

## Model Router (Fase 2)

`ai_gateway/router.py`. `TASK_PROVIDER: dict[str, str]` maps each task name
to `"anthropic"` or `"gemini"` — every task that existed before Fase 2
(`business_analysis`, `message_generation`, `site_diagnostic`) defaults to
`"anthropic"`, so adding Gemini changed zero production behavior until a
task is deliberately moved. Per spec section 18's guidance for future
tasks: Gemini for high-volume classification/extraction/multimodal/cheap
pre-filtering, Claude for synthesis and reasoning-heavy work.
`get_provider_for_task(task)` raises `ProviderNotConfigured` (not a silent
fallback) when the routed provider's API key isn't set.

## Providers

**Anthropic** (`anthropic_provider.py`, default for all tasks today).
Structured output via forced tool use — the request's Pydantic schema
becomes a single forced tool, and the tool-call input is validated against
that schema before being returned. A `ValidationError` becomes an
`AIProviderError` — invalid output is never silently passed through (spec
section 37).

`ai_gateway/anthropic_provider.py`. Structured output is enforced via tool use
— the request's Pydantic schema becomes a single forced tool
(`tool_choice={"type": "tool", ...}`), and the tool-call input is validated
against that same schema before being returned. A `ValidationError` becomes an
`AIProviderError` — invalid output is never silently passed through (spec
section 37).

Model selection per task (spec section 39 — cheapest model that does the job):

- `claude-haiku-4-5-20251001` — default. Cheap/fast tasks: normalization,
  classification.
- `claude-sonnet-5` — reasoning-heavy tasks (business analysis, message
  generation), passed explicitly via `AIRequest.model` when a caller needs it.

Per-model USD pricing lives in `_PRICING_PER_MILLION_TOKENS` in
`anthropic_provider.py`, next to where it's used — update it there when prices
change.

**Gemini** (`gemini_provider.py`, second provider, Fase 2). Structured
output via `response_mime_type: "application/json"` + `response_schema`
(Google's own native JSON-schema mode, not tool use) — the raw JSON is
independently re-validated against the Pydantic schema here too, same
discipline as Anthropic, rather than trusting the SDK's own `response.parsed`.
Default model `gemini-3.1-flash-lite` — cheapest current (non-retiring)
model, matching the "cheap/high-volume" role spec section 18 gives Gemini.
Real finding from Fase 2: Gemini 2.5 models (including the even-cheaper 2.5
Flash-Lite) are scheduled for retirement 2026-10-16 — deliberately not used
as the default despite being cheaper. Pricing table fetched directly from
`ai.google.dev/gemini-api/docs/pricing` (third-party aggregators disagreed
with each other during this research, so none were trusted) — verify again
before relying on it for real budgeting.

## Cost control (spec section 39)

Before this module is even called, a caller should have already: checked
whether the task is deterministic (most of Website Analysis is — no AI
needed), checked cache, and minimized context. None of that is enforced by
`ai_gateway` itself — it's a per-caller discipline documented here so it isn't
forgotten as Discovery/Enrichment/Analysis land in later phases.

## Real finding (Fase 2): installing the Gemini SDK broke real Anthropic calls

`google-genai` pulls in `httpx>=0.28`, which removed the `proxies` kwarg the
installed `anthropic` SDK (0.39) passed internally — every mocked test still
passed (they never touch the real SDK), but a real Anthropic call failed
outright. Only found by making one for real. Fixed by upgrading `anthropic`
to `>=1.4,<2` (confirmed compatible with httpx 0.28, and its public API —
`AsyncAnthropic`, `.messages.create`, `anthropic.APIError` — is unchanged).
Lesson kept here on purpose: adding a second provider's dependency is not
risk-free for the first one, even when nothing in *this* codebase changed.

## What exists

Fase 0: the gateway itself (interface, cost logging to `ai_calls`, unit
tests against a mocked provider — no real spend in the automated suite).
Fase 2: the Model Router and a second real provider (Gemini), with fallback
built and tested but dormant for every task already in production (see
`TASK_FALLBACK` above) until a future phase validates output quality on the
other model and opts a specific task in.

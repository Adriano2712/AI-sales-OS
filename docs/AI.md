# AI Gateway

`apps/api/src/app/modules/ai_gateway/`

## Interface

Domain code never imports a provider SDK directly. It builds an `AIRequest`
(task name, system/user prompt, a Pydantic `output_schema`) and calls
`ai_gateway.service.run_ai_task(db, provider, tenant_id, request)`, which:

1. Calls `provider.generate(request)`.
2. Logs the outcome to `ai_calls` — success or failure, unconditionally, so
   cost visibility never depends on a caller remembering to log it.
3. Returns the schema-validated output, or re-raises `AIProviderError`.

Swapping providers means writing a new `AIProvider` implementation
(`ai_gateway/base.py`); nothing outside `ai_gateway/` changes.

## Default provider: Anthropic

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

## Cost control (spec section 39)

Before this module is even called, a caller should have already: checked
whether the task is deterministic (most of Website Analysis is — no AI
needed), checked cache, and minimized context. None of that is enforced by
`ai_gateway` itself — it's a per-caller discipline documented here so it isn't
forgotten as Discovery/Enrichment/Analysis land in later phases.

## What exists vs. what's planned

Phase 0 ships the gateway itself, cost logging, and unit tests (mocked
provider — no real Anthropic calls in the test suite, matching the
no-unnecessary-spend principle). No real AI call has been made against this
code yet; that starts in whichever phase first needs a scored analysis
(Business Analysis, Phase 5).

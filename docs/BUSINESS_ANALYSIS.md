# Business Analysis

**Status: built (Fase 5).** First phase that actually calls the AI Gateway.

```
Company -> BUSINESS_ANALYSIS job -> deterministic scores + AI Analyst -> BusinessAnalysis
```

Chained automatically (spec section 39 cost-gate applies to *when* this
fires, not just *whether*):
- No website: `jobs/handlers/discovery.py` enqueues `BUSINESS_ANALYSIS`
  directly, right after enrichment.
- Has website: `jobs/handlers/website_analysis.py` enqueues it after the
  crawl completes, so the AI Analyst gets a fresh `digital_score` to reason
  about instead of stale/missing data.

## Deterministic vs AI (spec section 39: don't call AI when a rule answers it)

Explicit, approved trade-off from Fase 5 planning — 3 of the 5 spec-section-33
sub-scores are computed with **no AI call**, because they're directly
derivable from data already collected:

| Score | How | AI? |
|---|---|---|
| `digital_maturity_score` | `0` if no website; otherwise mirrors Fase 4's `digital_score` | No |
| `activity_score` | fraction of {phone, website, opening_hours evidence} found | No |
| `need_score` | `100 - digital_maturity_score` | No |
| `business_fit_score` | AI Analyst's judgment | Yes |
| `compatibility_score` | AI Analyst's judgment | Yes |

`overall_score` combines all 5 with spec section 33's weights (Perfil 20%,
Atividade 20%, Maturidade digital 20%, Necessidade 25%, Compatibilidade 15%),
renormalized over whichever dimensions are actually known — same pattern as
Fase 4's `digital_score`.

## AI Analyst

`app/modules/business_analysis/ai_analyst.py`. Model: `claude-sonnet-5`
(reasoning-heavy — this is synthesis and judgment, not classification, so
Haiku isn't the right tool here per `docs/AI.md`'s per-task model guidance).

Input (built by `build_ai_request`, pure — no I/O): company name/segment/
location, the 3 deterministic scores, Fase 4's website sub-scores, and every
`Evidence` claim collected so far with its confidence.

Output (`BusinessAnalysisAIOutput`, schema-validated per spec section 37):
`business_fit_score`, `compatibility_score`, `confidence` (0-100, *never*
conflated with the scores themselves — spec section 42), `findings[]`,
`problems[]` (max 8 each). The system prompt explicitly instructs the model
to say "insufficient evidence" rather than invent specifics, and to keep
`confidence` about evidence quality, not business quality.

Every finding and problem also becomes its own `Evidence` row
(`source="ai_analyst"`, `confidence=MEDIUM`) — the AI's output is itself
traceable evidence for whatever later reads it (Opportunity Engine, Fase 6),
same as everything else in the Evidence Engine.

## Cost control (spec section 39)

- **Idempotent by default**: `analyze_business` returns the existing
  analysis if one already exists for the company — a re-triggered/duplicate
  job never calls the AI twice. Verified with a real test that counts calls
  across two separate job invocations.
- Real measured cost (Fase 5 manual validation, 3 companies, Sonnet):
  ~$0.010–0.013 per business analysis (1,300-1,450 input tokens, 380-570
  output tokens each). Logged per-call in `ai_calls` (provider, model,
  tokens, latency, `estimated_cost_usd`) since Fase 0 — this is real data,
  not an estimate, useful for spec section 71's cost tracking ahead of Fase 9.

## Real finding

Ran the AI Analyst for real against **Dextraining** (Fase 4's example of a
company whose website was down — `digital_score=0`, everything else
`UNKNOWN`). The model correctly:
- read `need_score=100` / `digital_maturity_score=0` as a real signal,
- explicitly flagged "Insufficient public evidence to assess company size...
  service offerings... customer base" rather than inventing detail,
- returned `confidence=30` (low) alongside `overall_score=62.7` — exactly
  spec section 42's worked example ("potentially good opportunity, but
  limited evidence"), produced from real data, not a synthetic test case.

## Data model

`business_analyses` — append-only (one row per run, like `website_analyses`).

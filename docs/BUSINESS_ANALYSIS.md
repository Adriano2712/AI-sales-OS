# Business Analysis

**Status: built (Fase 5). service_fit_score/buying_potential added (master-plan Fase 6).**
First phase that actually calls the AI Gateway.

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

## Master-plan Fase 6: SERVICE_FIT_SCORE + BUYING_POTENTIAL

**`SERVICE_FIT_SCORE`** answers a different question than `business_fit_score`:
not "is this a good prospect for a software house in general" but "does this
company fit the *specific* service(s) this campaign is selling". Requires a
"what are we selling" concept that didn't exist anywhere in the codebase
before this phase — added as `Campaign.services: list[str]` (ICP field,
`campaigns/models.py`), resolved for a company via `Company.campaign_run_id
-> CampaignRun.campaign_id -> Campaign.services`
(`business_analysis/service.py::_get_campaign_services`). A company created
outside a campaign run, or a campaign that never states its services, falls
back to the exact same generic software-house description
`business_fit_score` was already scored against before this field existed
(`ai_analyst.py`'s `_DEFAULT_SERVICES`) — so an unset `services` list doesn't
fabricate a service-specific number, it just makes `service_fit_score` track
`business_fit_score` closely, which is honest.

**`BUYING_POTENTIAL`** (`buying_potential_score` + `buying_potential_summary`)
describes the *strength of observed signals* (digital gaps, activity level,
review volume, etc.) — never a claim about what a business wants, intends,
or has decided. This is enforced in code, not just prompted: a
`field_validator` on `BusinessAnalysisAIOutput.buying_potential_summary`
rejects a denylist of assertive purchase-intent phrases in English and
Portuguese ("wants to buy", "quer comprar", "ready to buy", ...) before the
output is ever trusted — same discipline as `evidence/service.py`'s
`InvalidEvidencePolarity` check for the Opportunity Signal's own absolute
rule. `buying_potential_summary` becomes an `Evidence` row like
findings/problems, but with `NEUTRAL` polarity always — mapping
buying-potential *strength* to a POSITIVE/NEGATIVE opportunity judgment
would mean inventing a threshold this phase wasn't asked to define (that
weighting belongs to Opportunity Score 2.0, a later phase).

Both fields are additive to `BusinessAnalysis` and `BusinessAnalysisAIOutput`
— confirmed non-breaking for `opportunities/service.py::score_company`,
which only reads `business_fit_score`/`activity_score`/`need_score`/
`confidence`/`problems` by name and doesn't iterate the model's full field
set. Wiring `service_fit_score`/`buying_potential_score` into opportunity
scoring itself is deliberately deferred to Fase 7 (Opportunity Score 2.0).

**Real end-to-end validation**: created a real `Campaign` (`services=
["online scheduling", "patient reminders"]`) + `CampaignRun` + `Company`
against the live database, ran `analyze_business` for real, and confirmed
the campaign's own services (not the generic fallback) reached the AI
prompt verbatim, the returned `service_fit_score`/`buying_potential_score`/
`buying_potential_summary` persisted correctly, and the buying-potential
Evidence row was recorded as `NEUTRAL`/`BUSINESS_ANALYSIS` — then cleaned up.

## Data model

`business_analyses` — append-only (one row per run, like `website_analyses`).

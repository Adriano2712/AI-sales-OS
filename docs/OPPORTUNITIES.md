# Opportunity Engine

**Status: built (Fase 6).** No AI call — spec section 40 says the Opportunity
Score is "calculado pelo backend"; every input it needs already exists in
`BusinessAnalysis` (Fase 5), so recomputing or re-asking the AI Analyst here
would violate spec section 39's cost-control rule ("verificar se a tarefa
pode ser determinística" before calling AI).

```
BusinessAnalysis -> SCORING job -> deterministic score + type + text -> Opportunity
```

Chained automatically: `jobs/handlers/business_analysis.py` enqueues
`SCORING` right after a `BusinessAnalysis` is created — the one point a fresh
one always exists.

## Score components (spec section 40)

| Component | Source | Notes |
|---|---|---|
| `digital_gap` | `BusinessAnalysis.need_score` | already `100 - digital_maturity_score` from Fase 5 |
| `business_fit` | `BusinessAnalysis.business_fit_score` | AI Analyst's judgment, unchanged |
| `need` | `(need_score + (100 - activity_score)) / 2` | averages two independent "needs help" signals — digital + visible commercial activity — over whichever is known |
| `commercial_signals` | `BusinessAnalysis.activity_score` | unchanged |

`opportunity_score` is a renormalized weighted average of the 4 components
(25% each, configurable — same never-fill-a-gap-with-a-guess pattern as Fases
4-5's scores). `confidence` is carried straight through from
`BusinessAnalysis.confidence` and never blended into the score itself (spec
section 42: score != confidence).

## Classification (spec section 41)

```
90-100 -> HIGH
75-89  -> GOOD
60-74  -> REVIEW
0-59   -> LOW
```

Thresholds configurable (`opportunities/scoring.py`).

## Type (spec section 44) — honest, not exhaustive

Only `WEBSITE` is ever assigned by rule (when `digital_maturity_score < 50`
— real, measured evidence). Every other spec type
(`E_COMMERCE`/`AUTOMATION`/`INTERNAL_SYSTEM`/`INTEGRATION`/`DIGITAL_PRESENCE`)
would need signals this pipeline doesn't collect yet; guessing one would
violate spec section 35's anti-hallucination rule. Everything else falls
back to `OTHER`. `potential_solution` is templated text that only fires for
`WEBSITE` — same reasoning, not invented for a type with no supporting
signal.

## Idempotency (spec section 54)

One `Opportunity` per `(tenant_id, company_id, type)` — `UNIQUE` constraint,
enforced by an upsert in `opportunities/service.py:score_company`. Rerunning
`SCORING` for the same company updates the existing row in place rather than
creating a duplicate. Unlike `WebsiteAnalysis`/`BusinessAnalysis` (append-only
history), an Opportunity is a record a human works — it has a `status` a
person moves through `OPEN -> REVIEWING -> APPROVED/REJECTED/ARCHIVED`
(`PATCH /api/v1/opportunities/{id}`), so recomputing its score on a pipeline
re-run must not spawn a fresh row.

## API

`GET /api/v1/opportunities` — filters from spec section 46: `segment`,
`city`, `status`, `type`, `min_score`. Default view hides `ARCHIVED`, same
"still worth looking at" pattern as `Company`'s default hiding
`INVALID`/`DUPLICATE`. Response includes the company's name/segment/city
(spec section 46's dashboard fields) via a per-row lookup — fine at this
project's scale (spec section 9: dozens of companies per campaign, not
thousands).

`GET /api/v1/opportunities/{id}` / `PATCH /api/v1/opportunities/{id}` —
detail + status update.

## Out of scope this phase

`Suggested Offer` / `Suggested Message` (spec section 45) are explicitly
Fase 8 (SDR Assistido, spec sections 47-48) — message generation is its own
job type and its own human-approval gate, not something Fase 6 should
anticipate.

## Real finding

Ran the real deterministic pipeline (no mocks, real dev tenant) against the
3 companies that already had a real `BusinessAnalysis` from Fase 5
(Dextraining, IMED, Saúde Ocupacional de Sorocaba — all in Campinas/Sorocaba).
All 3 classified `WEBSITE` type (all have `digital_maturity_score` under the
50 threshold — Dextraining's site is down, the other two have no website at
all) and `REVIEW` classification (scores 63.8-73.8, confidence 25-30% — low
confidence correctly keeps them out of `HIGH`/`GOOD` despite a decent raw
score, exactly spec section 42's worked example). `potential_solution` came
back correctly differentiated: "criar um site" for the two with no website
vs. "modernizar o site existente" for Dextraining.

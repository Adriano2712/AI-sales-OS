# Opportunity Engine

**Status: built (Fase 6), Opportunity Score 2.0 added (master-plan Fase 7).**
No AI call — spec section 40 says the Opportunity
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

## Sales-pipeline outcome (`outcome` / `outcome_notes`, post-Fase-8)

Separate axis from `status` — `status` is "is this opportunity still worth
working" (a human's internal triage), `outcome` is "how far did the real
deal get" (`CONTACTED -> REPLIED -> PROPOSAL_SENT -> WON/LOST`), logged by
hand as it happens outside the system, same as `Message.response` — there's
still no real send/reply integration (Fase 8). No transition rules enforced
(same reasoning as `Company.status`/`do_not_contact`): any value is
reachable from any other, since this reflects reality a human corrects, not
a system-driven workflow. `PATCH /api/v1/opportunities/{id}` accepts
`outcome`/`outcome_notes` independently of `status` — updating one never
touches the other. Exists specifically to validate the pipeline end to end
(does a HIGH/GOOD-classified opportunity actually convert more than a LOW
one?) before investing further in scaling discovery volume.

## Out of scope this phase

`Suggested Offer` / `Suggested Message` (spec section 45) are explicitly
Fase 8 (SDR Assistido, spec sections 47-48) — message generation is its own
job type and its own human-approval gate, not something Fase 6 should
anticipate.

## Master-plan Fase 7: Opportunity Score 2.0

The original 4-component formula above (`digital_gap`/`business_fit`/
`need`/`commercial_signals`, `WEIGHTS`, `compute_opportunity_score`) is kept
exactly as it was — still unit tested, still the source of `Opportunity`'s
own `digital_gap`/`business_fit`/`need`/`commercial_signals` columns (API
backward-compatibility). `opportunity_score`/`confidence` themselves now
come from a richer blend that finally consumes the signals every phase
since Fase 3 deliberately deferred here.

**9 factors** (`opportunities/scoring.py::OpportunityFactors`,
`compute_opportunity_factors`): the original 4, plus `service_fit`
(Fase 6's `service_fit_score`), `buying_potential` (Fase 6's
`buying_potential_score`), `website_opportunity` (Fase 5's
`WebsiteAnalysis.opportunity_score` — the CTA/conversion-gap number, not
the overall quality score), `customer_validation` (presence-only, 100 when
the company has real Google review data at all — same design decision
Fase 4 already made for the underlying evidence: a star rating's actual
*value* is never judged, only whether real third-party validation exists),
and `evidence_signal_balance` (new: `evidence/service.py::
compute_signal_balance`, a confidence-weighted POSITIVE-vs-NEGATIVE balance
across every `Evidence` row for the company — NEUTRAL/UNKNOWN evidence
never tips it either way, the Fase 3 absolute rule extended to
aggregation). Same renormalize-over-known-factors discipline as every
other score in this project — a factor that can't be evaluated is
excluded, never guessed.

**Weights configurable per campaign**: `Campaign.opportunity_weights`
(nullable JSON, validated via `opportunities/schemas.py::
OpportunityWeights`) overrides `DEFAULT_WEIGHTS_V2` per factor — omitted
factors keep the system default rather than silently becoming zero-weight.
Resolved per company via the same `Company.campaign_run_id ->
CampaignRun.campaign_id -> Campaign` join Fase 6 already established for
`services`. A company outside any campaign, or a campaign that never sets
its own weights, scores against the system defaults.

**Penalties, subtracted after the weighted average, not blended into it**
(`compute_penalties`/`apply_penalty`, fixed system-wide constants, not
per-campaign — a smaller, more universally-true set than factor weights):
`CompanyStatus.INVALID`/`DUPLICATE` (-60, spec's "apparently closed
business"), `do_not_contact` (-30), an opportunity that already has a
tracked `outcome` (-20, spec's "already-existing/contacted opportunity").
Clipped at 0 — a penalty can zero out a score, never invert it. "Out of
ICP" is explicitly *not* a penalty here: no ICP-matching engine exists yet
(Fase 6 deliberately added only `Campaign.services`, not the full ICP field
set, to avoid unused columns) — inventing a matching/threshold system for
fields that don't exist would be exactly the kind of scope creep this
project's phased protocol exists to prevent.

**OPPORTUNITY_CONFIDENCE**, genuinely separate now (`compute_opportunity_
confidence`): blends the AI Analyst's own `BusinessAnalysis.confidence`
with how *complete* the 9-factor picture actually was (evaluated factors /
9) — no longer a naive pass-through. A score built from 2 of 9 known
factors gets meaningfully lower confidence than an identical-looking score
built from 8 of 9, even with the same AI confidence input.

**`score_components`** (new `Opportunity` column, JSON): the full
breakdown behind every score — raw per-factor values, the weights actually
used (campaign override or defaults), penalty points/reasons, and the
original v1 formula's result for comparison. Transparency/debugging only,
never itself read back into scoring.

**Real end-to-end validation** (live database, three scenarios): (1) a
minimal company with only 4 of 9 factors known scored `opportunity_score=
77.7`, `confidence=24.4` (`= 55.0 × 4/9`, confirming the completeness
scaling); (2) an `INVALID` + `do_not_contact` company with an otherwise
strong raw score (86.0) was correctly penalized to `opportunity_score=0.0`
(penalty 90 = 60 + 30, clipped rather than going negative); (3) a campaign
with `opportunity_weights={"business_fit": 1.0, ...everything else 0.0}`
scored a company purely on `business_fit_score=100` (`opportunity_score=
100.0`), ignoring `digital_gap=0`/`need=0` that would otherwise have
dragged the default-weighted score down. All three cleaned up after.

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

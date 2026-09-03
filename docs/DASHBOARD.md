# Dashboard

**Status: built (Fase 7).** Answers spec section 46's question — "Com quem
devo falar?" — by completing what Fase 6's `/opportunities` page already
covered, not duplicating it.

```
GET /api/v1/opportunities (score/confidence/segment/city/status/type filters)
GET /api/v1/dashboard/summary (tenant-wide metrics rollup)
```

## What Fase 6 already had vs. what this phase added

| Spec section 46 field | Source |
|---|---|
| oportunidade, score, empresa, segmento, cidade, problema | Fase 6 |
| filtro por score, segmento, cidade, status, tipo | Fase 6 |
| **filtro por confidence** | Fase 7 — `min_confidence` added to `list_opportunities` |
| **solução** in the list (not just detail) | Fase 7 — now a column |
| **próxima ação** | Fase 7 — new |

## next_action — deterministic, not stored

`opportunities/scoring.py:derive_next_action(status)` maps an
`OpportunityStatus` straight to a Portuguese action string. It's computed at
response time, not a database column — there's nothing here an AI call or a
guess could add (spec section 35): the "next action" for an `OPEN`
opportunity is always "review it," full stop.

## Metrics (spec section 83)

`GET /api/v1/dashboard/summary` aggregates, tenant-wide, with **no new
collection** — pure SQL sums/counts over data every earlier phase already
wrote:

- **Discovery**: sums `CampaignRun`'s own counters (`companies_found`,
  `companies_validated`, `duplicates`, `enriched`, `analyzed`) across every
  campaign run for the tenant.
- **Opportunity**: total count + count by `classification`.
- **Cost**: real sum of `ai_calls.estimated_cost_usd` (not an estimate —
  logged per-call since Fase 0).

**Sales metrics (approved/contacted/replied/...) are deliberately absent.**
There's no sales pipeline yet (Fase 8+) — showing fixed zeros would be noise
dressed up as data, which is exactly what spec section 35 says not to do.

## Real finding

Ran the real summary against the dev tenant: `opportunities.total=3`,
`review=3` (matches Fase 6's real result — all 3 scored companies landed in
`REVIEW`), `cost.total_estimated_cost_usd=0.034` across 3 `ai_calls` (matches
Fase 5's measured ~$0.010-0.013/analysis). But `discovery.companies_found=0`
despite the tenant having 16 real companies — its one `CampaignRun` row is
stuck `PENDING` with all counters at 0. The 16 companies exist (created
during earlier phases' real-infrastructure validation, not a completed
campaign run job), so this number is honestly reporting real database state,
not a Fase 7 bug — flagged for the user, not silently worked around.

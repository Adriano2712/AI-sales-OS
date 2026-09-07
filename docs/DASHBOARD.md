# Dashboard

**Status: built (Fase 7 API, Fase 11 frontend).** Answers spec section 46's
question — "Com quem devo falar?" — by completing what Fase 6's
`/opportunities` page already covered, not duplicating it.

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
- **Funnel** (post-Fase-8): count by `Opportunity.outcome`
  (`CONTACTED`/`REPLIED`/`PROPOSAL_SENT`/`WON`/`LOST`) — see
  docs/OPPORTUNITIES.md. Only ever as populated as what's actually been
  logged by hand (no send/reply integration exists), so an all-zero funnel
  honestly means "nothing tracked yet," not a bug.
- **Cost**: real sum of `ai_calls.estimated_cost_usd` (not an estimate —
  logged per-call since Fase 0).

Fase 12 extended this same endpoint with the rest of spec section 83
(invalid companies, enrichment success rate, average scores, approved
count, cost-per-unit breakdowns) and added a separate `/analytics` frontend
page for the full breakdown — see docs/ANALYTICS.md. `/dashboard` itself
keeps showing only the subset relevant to "quem devo falar" (spec section
46), not the full metrics dump.

## Fase 11 — closing the frontend gap

`apps/web/src/app/(app)/dashboard/page.tsx` (the real page rendering this
data) was last touched before Fase 2 and never picked up `problem` — spec
section 46 lists "problema" as a required dashboard field, right alongside
"solução", but the table only ever rendered `potential_solution`. The API
(`OpportunityRead.problem`) and the frontend type
(`OpportunityDetail.problem`) already carried it — `/opportunities/[id]`
already renders it — it just wasn't wired into the dashboard table. Added
the missing "Problema" column, same `opportunity.problem ?? "—"` pattern
already proven correct on the detail page. No backend change, no new
endpoint, no schema change: every other spec section 46 field and filter
(score, confidence, empresa, segmento, cidade, solução, próxima ação;
filters for score/confidence/segmento/cidade/status/type) was already
correctly wired.

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

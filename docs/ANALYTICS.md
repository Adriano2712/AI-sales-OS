# Analytics

**Status: built (Fase 12).** Master prompt section 12 lists `Analytics` as
its own architecture module, and section 14 lists it as its own frontend
nav item, separate from `Dashboard` — but section 83 ("MÉTRICAS") is the
only place the *content* of that module is actually specified, and
`GET /api/v1/dashboard/summary` already implemented most of it (see
docs/DASHBOARD.md). Rather than standing up a competing `analytics` backend
module that duplicates the same aggregation logic under a different name,
Fase 12 **extended the existing summary endpoint** with the section-83
metrics it was still missing, and added the separate `/analytics` frontend
page section 14 calls for — one metrics source, two frontend views with
different jobs (`/dashboard` = "who do I talk to", a ranked opportunity
list; `/analytics` = the full section-83 metrics breakdown, no opportunity
list).

```
GET /api/v1/dashboard/summary   (unchanged endpoint, extended response)
```

## What was actually missing vs. spec section 83

| Section 83 group | Field | Status before Fase 12 |
|---|---|---|
| Discovery | companies_found/validated/duplicates | already had (Fase 7) |
| Discovery | **invalid** | missing — added |
| Enrichment | **website_found / website_not_found / (success rate)** | missing — added |
| Analysis | companies_analyzed | already had, under `discovery.analyzed` |
| Analysis | **average_digital_score / average_business_fit** | missing — added |
| Opportunity | created/high/good/review | already had (Fase 7) |
| Sales | contacted/replied/proposals/won/lost | already had (Fase 8, as `funnel`) |
| Sales | **approved** | missing — added |
| Sales | **meetings** | not trackable — see below |
| Cost | AI cost | already had (Fase 7) |
| Cost | **cost/company, cost/analysis, cost/opportunity** | missing — added |

## Definitions chosen (real data, no invented distinctions)

- **invalid**: `Company.status == INVALID`, tenant-wide. No `CampaignRun`
  counter exists for this — it's a real, distinct `Company` state
  (`companies/enums.py`), not something discovery run counters track.
- **website_found / website_not_found**: `Company.website IS NOT NULL`
  vs `IS NULL`, over every non-`DUPLICATE` company. A `DUPLICATE` row is the
  same real-world business as another row already counted elsewhere — the
  most important, and only plainly-stored, enrichment signal this codebase
  tracks per company is whether a website was found at all, so this is
  counted directly rather than inventing a separate "enrichment attempted"
  flag nothing writes.
- **success_rate**: `website_found / (website_found + website_not_found) *
  100`, one decimal. **Null** (not `0.0`) when there are zero non-duplicate
  companies — "nothing to measure" is not the same claim as "0% success".
- **average_digital_score / average_business_fit**: `AVG(WebsiteAnalysis.
  digital_score)` / `AVG(BusinessAnalysis.business_fit_score)`, tenant-wide.
  SQL `AVG` already skips `NULL`s for free — exactly right here, since a
  blocked/failed site legitimately stores `digital_score = NULL` (Fase 5's
  absolute rule: a failed observation is never scored, good or bad).
  **Null** when there are zero scored rows yet, not `0.0`.
- **approved**: `Opportunity.status == APPROVED`, tenant-wide — distinct
  from `outcome` (a human sales-pipeline stage); `status` is "is this worth
  working," and `APPROVED` already existed as a real status value.
- **meetings**: **always null.** No `OpportunityOutcome` value for a
  meeting exists anywhere in this codebase — no workflow sets one. Spec
  section 86's rule ("se não houver evidência, não invente") means this is
  reported as *not tracked*, never as a fabricated `0`. Typed `int | None`
  rather than a frozen `None` so real tracking can be added later without a
  breaking schema change.
- **cost_per_company / cost_per_analysis / cost_per_opportunity**: total
  `ai_calls.estimated_cost_usd` divided by `companies_found` /
  `analyzed` / total opportunities respectively. **Null** (not a
  divide-by-zero, not a misleading "$0.00") when the denominator is zero.

## Frontend

`/analytics` (new page, new sidebar nav item) renders all six section-83
groups as metric cards — Discovery, Enrichment, Analysis, Opportunity,
Sales, Cost — reusing the same `GET /api/v1/dashboard/summary` response
`/dashboard` already fetches. `/dashboard` itself is untouched beyond
Fase 11's "problema" column; it stays focused on the ranked opportunity
list per spec section 46, not the metrics breakdown.

## Real validation

The updated `test_dashboard_summary_aggregates_only_the_caller_tenants_data`
integration test ran for real against the live Supabase/Postgres database
(not skipped) by deriving `TEST_ADMIN_DATABASE_URL`/`TEST_DATABASE_URL` from
the project's existing `MIGRATIONS_DATABASE_URL`/`DATABASE_URL` — the first
time in this project's session history these integration tests have
actually executed instead of skipping for missing env vars. Every new
Fase 12 field was asserted against hand-computed expected values (1 invalid
company, 1 website found vs. 2 not found → 33.3% success rate, 1 business
analysis at business_fit_score=70.0, 1 website analysis at
digital_score=80.0, 1 approved opportunity, meetings=null, and all three
cost-per-unit breakdowns) and passed.

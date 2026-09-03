# Architecture

## Shape

Modular monolith. One FastAPI process serves the API; one or more RQ worker
processes handle async jobs; both share the same domain code
(`apps/api/src/app/modules/*`). No microservices — nothing here justifies that
complexity yet (see spec section 78).

```
apps/web (Next.js)  --HTTPS-->  apps/api (FastAPI)  <--RLS-scoped SQL-->  Postgres (Supabase)
                                       |
                                       v
                                    Redis  <-- workers/run.py (RQ)
```

`apps/web` never queries Postgres directly for business data — only the API
does. Supabase Auth is used only for authentication (issuing the JWT the API
verifies); authorization and tenant isolation live in the API + RLS.

## Module boundaries (`apps/api/src/app/modules/`)

Each module owns its own models, schemas, service functions, and (where it has
HTTP surface) dependencies. `app/api/v1/` is a thin routing layer that composes
these — it must not contain business logic.

- `auth` — maps a verified Supabase JWT to a local `User` row.
- `tenancy` — resolves `(user, tenant) -> role`, sets the RLS session
  variables, exposes `require_role()` for endpoint authorization.
- `jobs` — job records, RQ enqueue helpers, idempotency. `jobs/handlers/`
  holds the actual job bodies workers execute.
- `ai_gateway` — provider-agnostic AI interface + Anthropic implementation +
  cost/usage logging.
- `audit` — structured event log for the actions in spec section 60.

Phase 1+ adds `campaigns`, `discovery`, `companies`, `enrichment`,
`website_analysis`, `business_analysis`, `opportunities`, `sales`,
`analytics` alongside these, following the same shape.

## Why these specific choices

- **RQ over Celery**: the MVP's job volume (~100 companies per campaign run)
  doesn't need Celery's scheduling/routing machinery; RQ is simpler to run and
  debug. Revisit if volume or scheduling needs grow.
- **httpx + BeautifulSoup over Playwright** for the website crawler (Phase 4):
  covers static/server-rendered HTML, which is most restaurant/clinic/local
  service sites. Known gap: JS-heavy SPAs render incompletely. Accepted for
  the MVP; Playwright can be added behind the same crawler interface later if
  the Fase 9 experiment shows it's needed.
- **n8n deferred entirely**: FastAPI + RQ already cover every orchestration
  step in the spec's Fluxo Central. n8n only earns its place once there's a
  concrete glue-automation need (e.g. Slack notifications) that isn't already
  a job type.
- **Alembic over Supabase's schema UI**: keeps the schema portable and
  reviewable as code; Supabase Studio is used for inspection only.

## What Phase 0 deliberately does not include

Campaigns, Discovery, Companies, Enrichment, Website/Business Analysis,
Opportunities, Sales, Analytics — all of it. Phase 0 is only the foundation:
auth, tenancy, RLS, job infra, AI Gateway skeleton, logging, and the doc set.
See the root `README.md` for the phase list.

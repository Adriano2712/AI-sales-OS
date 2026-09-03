# Database

PostgreSQL 16 via Supabase. Alembic (`database/migrations/`) is the single
source of truth for schema — never edit tables by hand through Supabase Studio.

## Two roles, on purpose

Every environment needs **two** Postgres connection strings:

| Role | Used by | Bypasses RLS? |
|---|---|---|
| `postgres` (Supabase's default admin role) | Alembic only, via `MIGRATIONS_DATABASE_URL` | Yes (it owns the tables) |
| `ai_sales_os_app` (created by migration `0001`) | The FastAPI app and workers, via `DATABASE_URL` | No |

This split exists because RLS policies don't apply to a table's owner. If the
running app connected with the same role that owns the tables, every RLS
policy in this project would be silently bypassed and tenant isolation would
only be as strong as whatever `WHERE tenant_id = ...` clause a developer
remembered to write — exactly what spec section 64 says not to rely on.

## Applying migrations

From the repo root, with the API venv active (`apps/api/.venv`):

```
export DATABASE_URL=...        # from .env — used as the fallback if MIGRATIONS_DATABASE_URL is unset
export MIGRATIONS_DATABASE_URL=... # Supabase admin connection
export APP_ROLE_PASSWORD=...   # becomes ai_sales_os_app's password — must match DATABASE_URL
cd database/migrations
alembic upgrade head
```

`APP_ROLE_PASSWORD` is required by migration `0001` — it fails loudly if unset
rather than silently creating a passwordless role.

## Row-Level Security model

- **`tenants`**: no RLS. Only referenced via FK; never queried directly by
  tenant-scoped code.
- **`users`**: no RLS. Holds only `auth_user_id` + `email`, both already known
  to Supabase Auth for that user. Deliberately not gated on
  `request.user_id`, because it's the table the app queries *to establish*
  that identity in the first place — gating it on itself would be circular.
- **`memberships`**: RLS on `user_id = current_setting('request.user_id')`.
  `app.core.db.set_user_context()` sets that session variable right after the
  local `users` row is resolved, before memberships are queried — this is
  what lets a user discover their own tenant(s) without already knowing them.
  Only a `SELECT` policy exists; INSERT/UPDATE/DELETE have no policy for
  `ai_sales_os_app`, so they're denied by default. There's no
  membership-management endpoint yet (inviting a user, changing a role) — that
  work happens via the admin role until Fase 1+ adds one.
- **`jobs`, `audit_log`, `ai_calls`, `campaigns`, `campaign_runs`**: RLS on
  `tenant_id = current_setting('request.tenant_id')`, enforced on both
  `USING` (reads) and `WITH CHECK` (writes — a session scoped to tenant A
  cannot insert a row stamped `tenant_id = B`).
  `app.core.db.set_tenant_context()` sets that variable once the tenant is
  known (see `app.modules.tenancy.dependencies.get_tenant_db`).

Both session variables are set via `SET LOCAL` (through
`set_config(..., true)`), so they're transaction-scoped and never leak
between requests sharing a pooled connection.

## Entities

```
# Fase 0
tenants(id, name, created_at, updated_at)
users(id, auth_user_id, email, created_at, updated_at)
memberships(id, user_id, tenant_id, role, created_at, updated_at)
jobs(id, tenant_id, type, status, idempotency_key, payload, result, error, attempts, created_at, updated_at)
audit_log(id, tenant_id, event_type, payload, created_at, updated_at)
ai_calls(id, tenant_id, task, provider, model, tokens_input, tokens_output, latency_ms, estimated_cost_usd, status, error, metadata, created_at, updated_at)

# Fase 1
campaigns(id, tenant_id, name, segment, cities, state, country, target_quantity, filters, status, created_at, updated_at)
campaign_runs(id, tenant_id, campaign_id, started_at, finished_at, status, companies_found, companies_validated, duplicates, enriched, analyzed, opportunities, errors, created_at, updated_at)

# Fase 2
companies(id, tenant_id, name, normalized_name, segment, address, city, state, country, phone, website, status, needs_review, created_at, updated_at)
company_sources(id, tenant_id, company_id, provider, external_id, source_url, collected_at, data, created_at, updated_at)

# Fase 3
evidence(id, tenant_id, company_id, claim, source, source_url, collected_at, confidence, supporting_data, created_at, updated_at)

# Fase 4
websites(id, tenant_id, company_id, url, created_at, updated_at)
website_pages(id, tenant_id, website_id, url, page_type, http_status, title, meta_description, has_viewport_meta, has_contact_form, has_phone_link, has_email_link, has_whatsapp_link, has_nav, has_custom_stylesheet, word_count, error, fetched_at, created_at, updated_at)
website_analyses(id, tenant_id, website_id, digital_score, score_funcionamento, score_mobile, score_ux, score_conversao, score_conteudo, score_design, findings, analyzed_at, created_at, updated_at)

# Fase 5
business_analyses(id, tenant_id, company_id, business_fit_score, activity_score, digital_maturity_score, need_score, compatibility_score, overall_score, confidence, findings, problems, analyzed_at, created_at, updated_at)

# Fase 6
opportunities(id, tenant_id, company_id, type, status, problem, potential_solution, reasons, digital_gap, business_fit, need, commercial_signals, opportunity_score, confidence, classification, created_at, updated_at)
UNIQUE(tenant_id, company_id, type)

# Fase 8
messages(id, tenant_id, opportunity_id, channel, status, generated_text, sent_at, response, created_at, updated_at)
companies.do_not_contact  -- column added to Fase 2's companies table
```

Remaining product entities (`opportunities`, ...) are added in
their respective phases (see root `README.md` and
`.claude/skills/new-tenant-module/SKILL.md`), each following the same
pattern: `TenantScopedMixin` + a `tenant_isolation` RLS policy + an explicit
grant to `ai_sales_os_app` (the `ALTER DEFAULT PRIVILEGES` in migration 0001
means new tables get that grant automatically as long as the migration that
creates them runs under the same admin role).

## Testing RLS

`apps/api/tests/integration/test_rls_tenant_isolation.py` seeds two tenants
and asserts, at the database level, that a session scoped to tenant A cannot
read or write tenant B's rows — and that a session with *no* tenant context
set sees nothing (fails closed). Requires `TEST_ADMIN_DATABASE_URL` and
`TEST_DATABASE_URL` env vars pointed at a real test database with migrations
applied; skips with an explanatory message otherwise.

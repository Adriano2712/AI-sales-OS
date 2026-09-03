---
name: db-migrate
description: Applies Alembic migrations to the AI Sales OS Supabase database using the correct two-role pattern (admin role for DDL, restricted ai_sales_os_app role for the app), then verifies the restricted role actually has RLS enforced. Use when a migration needs to be applied, created, or rolled back.
---

# DB Migrate

Context: this project deliberately uses **two different Postgres roles** (see
`docs/DATABASE.md`). Getting this wrong doesn't fail loudly — it fails by
silently disabling the security model. Read that file if anything below is
unclear before proceeding.

- `MIGRATIONS_DATABASE_URL` — Supabase's admin/`postgres` role. Owns the
  tables. **Bypasses RLS.** Used only by Alembic.
- `DATABASE_URL` — the restricted `ai_sales_os_app` role, created by migration
  `0001`. No `BYPASSRLS`. This is what the running API and workers connect
  as, and what RLS policies actually restrict.

**Never run Alembic against `DATABASE_URL`.** If you do, migrations will
still "work" (DDL will just fail with a permissions error, which is at least
loud) — but the more dangerous mistake is running the *app* against
`MIGRATIONS_DATABASE_URL` by accident, which would silently bypass every RLS
policy in the system. Double-check which env var is set to what before
running anything.

## Applying migrations

1. Confirm required env vars are set (don't guess — check, and stop if
   missing rather than falling back to something that seems close enough):
   - `MIGRATIONS_DATABASE_URL`
   - `APP_ROLE_PASSWORD` — required by migration `0001` specifically; it
     raises `RuntimeError` if unset rather than creating a passwordless role.
     Generate one if this is a first run: `openssl rand -base64 24`.

2. From the repo root, with the API venv active:
   ```
   apps/api/.venv/Scripts/python -m alembic -c database/migrations/alembic.ini upgrade head
   ```
   (or `cd database/migrations && ../../apps/api/.venv/Scripts/python -m alembic upgrade head`)

3. **Verify, don't assume.** Connect with `MIGRATIONS_DATABASE_URL` and check
   the restricted role actually landed the way migration `0001` intends:
   ```sql
   SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'ai_sales_os_app';
   -- expect: rolbypassrls = false, rolsuper = false
   SELECT tablename, rowsecurity FROM pg_tables
   WHERE schemaname = 'public' AND tablename IN ('memberships', 'jobs', 'audit_log', 'ai_calls');
   -- expect: rowsecurity = true for all four
   ```
   If either check comes back wrong, do not consider the migration successful
   even if `alembic upgrade head` exited 0.

4. Run the RLS integration tests to prove isolation actually works end to
   end, not just that the flags are set:
   ```
   export TEST_ADMIN_DATABASE_URL=<the postgres/admin connection string>
   export TEST_DATABASE_URL=<the ai_sales_os_app connection string>
   export DATABASE_URL=$TEST_DATABASE_URL   # test_auth_me_endpoint.py checks this matches
   apps/api/.venv/Scripts/python -m pytest apps/api/tests/integration -v
   ```

## Creating a new migration

- Add/modify SQLAlchemy models under `apps/api/src/app/modules/*/models.py`
  first — models are the source of truth `env.py` imports from.
- Any new tenant-scoped table needs, in the same migration:
  - the table, with a `tenant_id` FK to `tenants.id` (via `TenantScopedMixin`)
  - `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;`
  - a `tenant_isolation` policy (`USING` + `WITH CHECK` on
    `tenant_id = current_setting('request.tenant_id', true)::uuid`) —
    copy the pattern from `database/migrations/versions/0001_initial.py`
    rather than reinventing it.
  - No manual `GRANT` needed for the new table specifically — migration
    `0001`'s `ALTER DEFAULT PRIVILEGES` already covers future tables created
    by the same admin role.
- Write a real `downgrade()`, not `pass` — mirror `0001`'s downgrade (drop
  policies before disabling RLS, drop in FK-dependency order).

## Rolling back

```
apps/api/.venv/Scripts/python -m alembic -c database/migrations/alembic.ini downgrade -1
```
Rolling back `0001` all the way also drops the `ai_sales_os_app` role — expect
to have to re-run `APP_ROLE_PASSWORD`-gated setup again on the next upgrade.

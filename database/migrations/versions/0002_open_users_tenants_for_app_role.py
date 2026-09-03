"""open users/tenants to the app role (Supabase enables RLS by default on new tables)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01

Discovered by running migration 0001 against a real Supabase project and
verifying with `pg_tables`/`pg_policies` (see docs/DATABASE.md "Verifying"):
Supabase's Postgres enables `rowsecurity` on every new table in `public` by
default, regardless of whether the migration that created it called
`ENABLE ROW LEVEL SECURITY`. `tenants` and `users` were deliberately left
without a tenant_isolation-style policy (see 0001's comments — `users` in
particular can't be gated on request.user_id without circularity), so with
RLS force-enabled and zero policies, Postgres denies ALL access to any
non-owner role. That silently broke `ai_sales_os_app` reading or inserting
into either table.

Fix: explicit permissive policies for `ai_sales_os_app` on both tables. This
keeps RLS technically "on" (satisfying Supabase's own security linter) while
restoring the Phase 0 design: these two tables are not tenant-scoped and were
never meant to be access-restricted for the app role.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "ai_sales_os_app"


def upgrade() -> None:
    for table in ("users", "tenants"):
        op.execute(
            f"""
            CREATE POLICY app_role_full_access ON {table}
            FOR ALL TO {APP_ROLE}
            USING (true)
            WITH CHECK (true);
            """
        )


def downgrade() -> None:
    for table in ("users", "tenants"):
        op.execute(f"DROP POLICY IF EXISTS app_role_full_access ON {table};")

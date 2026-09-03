"""initial: tenants, users, memberships, jobs, audit_log, ai_calls + RLS

Revision ID: 0001
Revises:
Create Date: 2026-08-31
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Restricted role the FastAPI app + workers connect as. Never granted BYPASSRLS,
# so RLS policies below are the real isolation boundary, not just app-level
# filtering (spec section 18 / 64). Migrations themselves run as the Supabase
# admin/owner role, which is unaffected by these grants.
APP_ROLE = "ai_sales_os_app"


def upgrade() -> None:
    # --- tenants -----------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- users (mirrors Supabase auth.users; not tenant-scoped) -------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("auth_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_users_auth_user_id", "users", ["auth_user_id"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_auth_user_id", "users", ["auth_user_id"])

    # --- memberships ---------------------------------------------------------
    membership_role = postgresql.ENUM(
        "ADMIN", "MANAGER", "SDR", "ANALYST", "VIEWER", name="membership_role"
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])

    # --- jobs ------------------------------------------------------------
    job_type = postgresql.ENUM(
        "PING",
        "DISCOVERY",
        "ENRICHMENT",
        "WEBSITE_ANALYSIS",
        "BUSINESS_ANALYSIS",
        "SCORING",
        "MESSAGE_GENERATION",
        name="job_type",
    )
    job_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", "RETRYING", "CANCELLED", name="job_status"
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "type", "idempotency_key", name="uq_job_idempotency"
        ),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])

    # --- audit_log -----------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])

    # --- ai_calls --------------------------------------------------------
    op.create_table(
        "ai_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("tokens_input", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_calls_tenant_id", "ai_calls", ["tenant_id"])
    op.create_index("ix_ai_calls_task", "ai_calls", ["task"])

    # --- restricted app role (idempotent) -----------------------------------
    app_role_password = os.environ.get("APP_ROLE_PASSWORD")
    if not app_role_password:
        raise RuntimeError(
            "APP_ROLE_PASSWORD must be set in the environment before running this "
            "migration — it becomes the login password for the restricted "
            f"'{APP_ROLE}' Postgres role that the API/workers connect as. Generate "
            "one (e.g. `openssl rand -base64 24`) and export it, or put it in "
            ".env alongside MIGRATIONS_DATABASE_URL. See docs/DATABASE.md."
        )
    # Trusted local operator input (env var), not attacker-controlled — plain SQL
    # string escaping is sufficient here; this isn't a request-path query.
    escaped_password = app_role_password.replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{escaped_password}'
                    NOBYPASSRLS NOSUPERUSER;
            ELSE
                ALTER ROLE {APP_ROLE} PASSWORD '{escaped_password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {APP_ROLE}', current_database());
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};"
    )
    op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};")
    op.execute(
        f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};
        """
    )

    # --- RLS -----------------------------------------------------------------
    # `users` is intentionally NOT RLS-restricted: it's the table the app queries
    # to resolve request.user_id in the first place (see set_user_context), so
    # gating it on that same variable would be circular. It only holds
    # auth_user_id + email, both already known to Supabase Auth for this user.
    for table in ("memberships", "jobs", "audit_log", "ai_calls"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    op.execute(
        """
        CREATE POLICY membership_self_select ON memberships
        FOR SELECT
        USING (user_id = NULLIF(current_setting('request.user_id', true), '')::uuid);
        """
    )
    # No INSERT/UPDATE/DELETE policy on memberships for APP_ROLE: with RLS enabled
    # and no matching policy, those operations are denied by default. Membership
    # management (inviting a user to a tenant, changing role) has no endpoint yet
    # — it happens via the admin/migrations role until that exists.

    for table in ("jobs", "audit_log", "ai_calls"):
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
            """
        )


def downgrade() -> None:
    for table in ("jobs", "audit_log", "ai_calls"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
    op.execute("DROP POLICY IF EXISTS membership_self_select ON memberships;")

    for table in ("memberships", "jobs", "audit_log", "ai_calls"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("ai_calls")
    op.drop_table("audit_log")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS job_status;")
    op.execute("DROP TYPE IF EXISTS job_type;")
    op.drop_table("memberships")
    op.execute("DROP TYPE IF EXISTS membership_role;")
    op.drop_table("users")
    op.drop_table("tenants")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_ROLE}') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};
                DROP ROLE {APP_ROLE};
            END IF;
        END
        $$;
        """
    )

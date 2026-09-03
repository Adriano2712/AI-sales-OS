---
name: new-tenant-module
description: Recipe for adding a new tenant-scoped domain module to AI Sales OS (model, RLS migration, router, tests) following the exact conventions established in Fase 0 — including the Supabase-default-RLS gotcha that caused a real bug there. Use whenever a phase (Campaigns, Companies, Discovery, Enrichment, ...) introduces a new tenant-scoped entity.
---

# New Tenant Module

Every phase from Fase 1 onward adds at least one new tenant-scoped entity.
They all follow the same shape — this skill is that shape, written down so it
doesn't have to be re-derived (and re-risked) each time. Read
`docs/DATABASE.md` and `docs/ARCHITECTURE.md` first if this is the first time
touching this codebase in a session.

## 1. Model (`apps/api/src/app/modules/<module>/models.py`)

Two gotchas found the hard way in Fase 1 (Campaigns), both silent until you
serialize a real row from a real Postgres connection — unit tests with no DB
won't catch either:

- **Any `datetime` column beyond `TimestampMixin` needs
  `mapped_column(DateTime(timezone=True), ...)` explicitly.** Leaving the type
  unspecified (`mapped_column(nullable=True)` on a `Mapped[datetime | None]`)
  makes SQLAlchemy infer a naive `TIMESTAMP WITHOUT TIME ZONE`, which then
  rejects any timezone-aware Python `datetime` (e.g. `datetime.now(UTC)`) at
  insert time with `DataError: can't subtract offset-naive and offset-aware
  datetimes` — even if the migration itself correctly declared the Postgres
  column as `TIMESTAMPTZ`. The DB column and the ORM's Python-side type must
  agree; migration correctness alone doesn't guarantee it.
- **`eager_defaults` is already handled globally** — `Base.__mapper_args__` in
  `app/core/db.py` sets it, so a column with `onupdate=func.now()` (anything
  using `TimestampMixin`) gets refreshed via `RETURNING` at flush time instead
  of needing a lazy-load. Don't override `__mapper_args__` on a new model
  unless you have a specific reason to — doing so replaces (not merges) the
  dict and silently loses this, reintroducing
  `MissingGreenlet: greenlet_spawn has not been called` the next time
  something mutates a row and immediately serializes it in the same request
  (the common create/update → `Read.model_validate(obj)` pattern every
  endpoint in this codebase uses).

```python
from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin

class Thing(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "things"
    # ... columns ...
```

`TenantScopedMixin` already gives you `tenant_id` with the FK to `tenants.id`
— don't redeclare it. Put enums (status, type) in `enums.py` next to the
model, as plain Python `str, enum.Enum` — **except** any field the master
spec explicitly says must stay configurable without a code deploy (segment,
city are the known examples so far, per spec section 9) — those are plain
`String` columns, not Python enums, validated at the application layer
instead.

## 2. Migration — the part most likely to introduce a security bug

Copy the pattern from `database/migrations/versions/0001_initial.py`, not
from scratch:

```python
op.create_table("things", ...)
op.create_index("ix_things_tenant_id", "things", ["tenant_id"])

op.execute("ALTER TABLE things ENABLE ROW LEVEL SECURITY;")
op.execute(
    """
    CREATE POLICY tenant_isolation ON things
    USING (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('request.tenant_id', true), '')::uuid);
    """
)
```

**Do not skip the explicit `ENABLE ROW LEVEL SECURITY` + policy even though
Supabase enables RLS by default on new tables.** That default-enable-with-
zero-policies is exactly what broke `users`/`tenants` in Fase 0 (see
migration `0002` and `docs/SECURITY.md`) — it fails *closed* (denies
everything) until a real policy exists, which is safe but useless without
this step. After running the migration, verify with the same query
`/db-migrate` uses:

```sql
SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'things';
SELECT policyname, cmd FROM pg_policies WHERE tablename = 'things';
```

You do **not** need a manual `GRANT` for the new table — migration `0001`'s
`ALTER DEFAULT PRIVILEGES` already covers tables created by future migrations
run under the same admin role. `ai_sales_os_app` gets SELECT/INSERT/UPDATE/
DELETE automatically.

Write a real `downgrade()` (drop policy → disable RLS → drop table), not
`pass`.

## 3. Schemas (`schemas.py`) and router (`app/api/v1/<module>.py`)

- Pydantic request/response models in `schemas.py` — never return the
  SQLAlchemy model directly from a route.
- Routes depend on `get_tenant_db` (not bare `get_db`) for anything that
  reads/writes this table — that's what actually sets
  `request.tenant_id` for the RLS policy to key off of. Using `get_db`
  directly on a tenant-scoped table is a bug: RLS will silently return zero
  rows (fails closed, but the endpoint will look "broken", not obviously
  insecure — that's the failure mode to watch for in review).
- Mutating routes (`POST`/`PATCH`/`DELETE`) depend on
  `require_write_access()` (or a more specific `require_role(...)` if the
  phase's spec calls for it); read routes just need `get_tenant_db`.
- Any state-machine field (e.g. campaign status) gets its transition rules in
  `service.py`, not inline in the route handler — that's what the unit tests
  in step 4 exercise directly.

## 4. Tests

- **Unit**: state-machine transitions (valid → valid succeeds, invalid →
  rejected) and any request-shape validation, with no DB — mirror
  `apps/api/tests/unit/test_jwt_auth.py`'s style (fast, mocked/local only).
- **Integration**: tenant isolation on the new table, same shape as
  `apps/api/tests/integration/test_rls_tenant_isolation.py` — seed two
  tenants, assert a session scoped to tenant A can't read/write tenant B's
  rows, assert a session with no tenant context sees nothing. This is not
  optional even if "it's basically the same as the Fase 0 tables" — RLS bugs
  are per-table (a missing policy on a new table isn't caught by another
  table's test).
- Register the module's router in `app/api/v1/router.py`.
- For an HTTP-level test (exercising the real router, not just service
  functions), reuse `tests/integration/conftest.py`'s `authenticated_client`
  fixture (provisions a real `users`+`memberships` row and returns a bearer
  token for a given tenant/role) and `stub_jwks`/`requires_matching_env` —
  don't re-derive JWT signing per test file, see
  `tests/integration/test_campaigns_api.py` for the pattern.
- In test cleanup, delete the *user* you created, not the membership: FKs on
  `memberships` cascade from both `user_id` and `tenant_id`, so an explicit
  membership delete is redundant and — worse — races the `two_tenants`
  fixture's own teardown (whichever runs first wins; the loser hits a
  harmless but noisy `SAWarning: DELETE statement ... 0 were matched`, found
  in Fase 1). Rely on the cascade instead of fighting fixture teardown order.
- `_dispose_app_engine` (autouse, in `tests/integration/conftest.py`) already
  handles a pytest-asyncio + async-engine gotcha for you — a module-level
  singleton engine's pooled connections get bound to whatever event loop
  created them, but pytest-asyncio gives each test function a fresh loop by
  default, so reusing the pool across tests raises `RuntimeError: Event loop
  is closed` in whatever test happens to run next. You don't need to do
  anything for this as long as your test lives under `tests/integration/` —
  just know it's why that fixture exists if you ever see that error.
- **`set_tenant_context` doesn't survive a `commit()`** — for reads *or*
  writes. It's implemented as `SET LOCAL`, transaction-scoped; a
  `session.commit()` ends that transaction, and the next statement starts a
  fresh one with no context set. On a write this surfaces loudly as
  `InsufficientPrivilegeError: new row violates row-level security policy`;
  on a **read it fails silently** — the query just returns zero rows (RLS
  fails closed), which looks exactly like "nothing was inserted" even when
  the insert genuinely succeeded a moment earlier in a different transaction.
  Found writing Fase 3's enrichment integration tests: each one seeded a
  company, committed, called `enrich_company` (worked once fixed) — then the
  *verification* `SELECT` right after the next commit came back empty for
  the same reason, and briefly looked like a second bug. Rule of thumb: every
  `commit()` on a tenant-scoped session needs a `set_tenant_context()` before
  the next tenant-scoped statement, full stop — including the assertion
  query at the end of a test. Production code already does this correctly
  (see `jobs/handlers/discovery.py`'s per-company loop) — the mistake was
  only ever in test code, but trivially easy to repeat.

## 5. Audit events

If the module's actions map to events already defined in
`app/modules/audit/enums.py` (`campaign_created`, `campaign_started`, etc. —
spec section 60 has the full list), call `audit.service.log_event(...)` at
the point of state change rather than adding parallel logging. If the phase
needs an event not yet in that enum, add it there — don't invent a
freestanding logging call for it.

## When this skill doesn't apply

Modules that aren't tenant-scoped (none currently — `users`/`tenants`
themselves are the only exceptions, and they're not something you'd add
another one of) don't need step 2's RLS policy. If you're ever unsure whether
a new table should be tenant-scoped, it almost certainly should be — every
product entity in the spec's data model (campaigns, companies, opportunities,
...) carries `tenant_id`.

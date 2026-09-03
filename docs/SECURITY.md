# Security

## Secrets

- Local: `.env` (gitignored), populated from `.env.example`.
- Never committed: `.env*` is in the root `.gitignore`; `apps/web/.gitignore`
  additionally excludes `.env.local`.
- The Supabase `service_role` key is never used by this codebase — the app
  connects to Postgres with the restricted `ai_sales_os_app` role instead (see
  docs/DATABASE.md). If a future integration genuinely needs `service_role`
  (e.g. an admin operation outside the request path), it must never be
  reachable from `apps/web`.
- Frontend env vars are limited to `NEXT_PUBLIC_*` (Supabase URL, anon key,
  API URL) — all safe to expose to the browser by design. No secret ever gets
  a `NEXT_PUBLIC_` prefix.

## AuthN / AuthZ

- Supabase Auth issues the JWT; `app.modules.auth.dependencies.get_current_user`
  verifies it before any claim is trusted. Verification is via this project's
  JWKS (`app.modules.auth.jwks`, cached in-memory, refreshed on an unknown
  `kid` to handle key rotation) — **not** a shared HS256 secret. This was
  discovered, not assumed: an initial HS256-shared-secret implementation
  passed every self-signed test but would have rejected every real login,
  because this Supabase project (observed to be the current default for new
  projects) signs tokens with ES256. The algorithm used for verification is
  read from the trusted JWKS record for the token's `kid`, never from the
  token's own header, which specifically defeats JWT algorithm-confusion
  attacks (a crafted symmetric-key token can't be verified against an
  asymmetric public key).
- Authorization is role-based (`app.modules.tenancy.enums.Role`), checked via
  `require_role()` / `require_write_access()` dependencies — never inferred
  from the frontend.
- Tenant isolation is enforced at the database layer via RLS (see
  docs/DATABASE.md), not just by query filters in the API.

## Defense in depth, not defense in one layer

Every tenant-scoped table is protected twice: the API only ever queries
through a session that has had `set_tenant_context()` called, *and* the
database itself would refuse to return or accept rows for the wrong tenant
even if that call were skipped by a bug. `test_no_tenant_context_hides_all_rows`
in the integration suite tests specifically for the "forgot to set context"
case — the database must fail closed (see nothing), not open (see
everything).

## LGPD

- Discovery/Enrichment collect two categories of data that must stay
  distinguishable in the schema: **public business information** (company
  name, business address, business phone/website) vs. **personal data**
  (a named contact's phone/email, a decision-maker's name). Phase 2+ models
  must carry that distinction explicitly, not conflate them into one
  `contacts` blob.
- Minimization: don't collect a field just because a provider makes it
  available — only what a later stage (analysis, outreach) actually uses.
- `do_not_contact` (spec section 50) is a hard stop the system must check
  before any outreach action, from the first phase that adds outreach.
- Specific legal questions (retention periods, deletion requests, lawful
  basis for a given data category) are flagged for human legal review, not
  decided in code.

## What's tested so far (Phase 0)

- JWT validation: missing token, tampered signature, missing claims, wrong
  audience (`tests/unit/test_jwt_auth.py`).
- Tenant isolation via RLS, both read and write paths, plus the fail-closed
  no-context case (`tests/integration/test_rls_tenant_isolation.py` — needs a
  live test database; see docs/DATABASE.md).
- Membership self-select RLS (a user only sees their own memberships).

Not yet covered (later phases): IDOR on product resources (none exist yet),
rate limiting, dependency scanning.

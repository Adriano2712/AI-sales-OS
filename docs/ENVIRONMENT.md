# Environment Setup

## Prerequisites

- Node.js >= 20 (developed against v24)
- pnpm (installed here via `npm install -g pnpm` — `corepack enable` failed on
  this machine due to a Windows permission error writing to `Program Files`;
  the npm global install is a fine substitute)
- Python 3.12
- A Supabase project (free tier) — provides Postgres + Auth
- An Upstash Redis database (free tier) — or any Redis 7 instance
- An Anthropic API key

Docker is intentionally **not** required for Phase 0 — see the "no Docker"
decision in the Phase 0 report. If you'd rather run Postgres/Redis locally via
Docker later, that only changes what `DATABASE_URL`/`REDIS_URL` point to;
nothing else in this doc changes.

## First-time setup

1. **Supabase**: create a project. From Project Settings, collect:
   - Project URL → `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` (also embedded in
     the `ref` claim of the anon key, if you ever lose track of it)
   - `anon` public key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - Database password (the one you set at project creation) → part of
     `MIGRATIONS_DATABASE_URL`
   - No JWT secret to collect — the API verifies tokens via this project's
     JWKS endpoint (`SUPABASE_URL/auth/v1/.well-known/jwks.json`), fetched at
     runtime. See docs/SECURITY.md.

2. **Upstash**: create a Redis database, copy its connection string into
   `REDIS_URL`.

3. **Anthropic**: create an API key → `ANTHROPIC_API_KEY`.

4. **Apify** (optional — second discovery provider alongside OSM): create
   an account at apify.com (free tier: $5/month credit), get your token from
   Settings → Integrations → `APIFY_API_TOKEN`. Without it, discovery runs
   OSM-only — nothing else changes. See docs/DISCOVERY.md.

5. Copy `.env.example` to `.env` at the repo root and fill in the values
   above, plus a generated `APP_ROLE_PASSWORD` (see docs/DATABASE.md).

6. **Backend**:
   ```
   cd apps/api
   python -m venv .venv
   source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
   pip install -e ".[dev]"
   ```

7. **Run migrations** — see docs/DATABASE.md.

8. **Frontend**:
   ```
   pnpm install   # from repo root — installs all workspace packages
   ```
   Create `apps/web/.env.local` with the `NEXT_PUBLIC_*` vars from `.env`.

9. **Seed a dev tenant + membership** for your own Supabase Auth user (sign up
   once via the login page first, then run `database/seeds/seed_dev_tenant.py`
   — see its docstring) so `/api/v1/auth/me` has something to resolve.

## Running things

```
# API
cd apps/api && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000 --app-dir src

# Worker
apps/api/.venv/Scripts/python workers/run.py

# Web
pnpm --filter web dev
```

## Running tests

```
# Backend unit tests (no external dependencies)
cd apps/api && .venv/Scripts/python -m pytest tests/unit -v

# Backend integration tests (needs a real test database — see docs/DATABASE.md)
export TEST_ADMIN_DATABASE_URL=...
export TEST_DATABASE_URL=...
export DATABASE_URL=$TEST_DATABASE_URL   # required by test_auth_me_endpoint.py
.venv/Scripts/python -m pytest tests/integration -v -n auto
```

`-n auto` (pytest-xdist) runs integration tests in parallel — each test seeds
its own tenant(s), so they don't collide, and most of the wall-clock time is
network latency to Supabase rather than CPU, so parallelizing helps a lot
(the suite went from ~10 minutes to ~2 on this machine as of Fase 4). Drop
`-n auto` only if you need serial output to debug a specific failure.

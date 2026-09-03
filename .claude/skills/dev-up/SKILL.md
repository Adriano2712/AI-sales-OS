---
name: dev-up
description: Starts the AI Sales OS API, worker, and web dev servers together with the correct venv/env wiring, and confirms each one is actually responding before reporting success. Use when the user wants to run, test, or see the app working locally.
---

# Dev Up

Three processes, three different environments. The goal isn't just "start
them" — it's confirming each one actually came up, since a silently-failed
background process is worse than an error you can see.

Prerequisite: `.env` at the repo root must be filled in (see
`docs/ENVIRONMENT.md`) — `DATABASE_URL`, `REDIS_URL`, `SUPABASE_URL`,
`SUPABASE_JWT_SECRET` at minimum for the API to even import. `apps/web` needs
its own `.env.local` with the `NEXT_PUBLIC_*` vars.

## 1. API

From the repo root:
```
apps/api/.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000 --app-dir apps/api/src
```
Run this with `run_in_background: true` (Bash tool) — it's a long-running
process. Then confirm it's actually up:
```
curl -s http://localhost:8000/api/v1/health
```
Expect `{"status":"ok"}`. If the import fails (missing env var, bad
`DATABASE_URL` syntax), uvicorn exits immediately — check the background
task's output rather than assuming it's still starting.

## 2. Worker

Uses the **same venv as the API** — `workers/run.py` imports
`app.modules.jobs.*` from `apps/api/src` (see `workers/README.md`, this isn't
a separate Python environment):
```
apps/api/.venv/Scripts/python workers/run.py
```
Also `run_in_background: true`. Confirm it connected to Redis by checking its
output for RQ's startup log line (`Worker rq:worker:... started, version ...`
/ `Listening on default...`) rather than assuming silence means success.

## 3. Web

From the repo root:
```
pnpm --filter web dev
```
`run_in_background: true`. Confirm with:
```
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```
Expect `200` (or a redirect to `/login`/`/dashboard` — 307/308 is also fine).

## Reporting status

Only say the app is "running" once all three have been positively confirmed
(health check, worker log line, HTTP response) — not just "processes
launched". If any of the three didn't come up, say which one and show the
actual error output, don't guess at the cause.

To actually exercise a flow end to end (not just "servers respond"), open
`http://localhost:3000/login`, sign in, and confirm `/dashboard` resolves the
tenant via `/api/v1/auth/me` — that requires a seeded dev tenant/membership
(see `database/seeds/seed_dev_tenant.py`).

## Stopping

These are background tasks started via the Bash tool — use `TaskStop` (or ask
the user) rather than leaving orphaned dev servers running across sessions.

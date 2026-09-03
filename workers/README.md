# Workers

RQ worker process. Job handlers are not defined here — they live in
`apps/api/src/app/modules/*/handlers/` alongside the domain code they operate on
(models, services, the RLS-aware DB session helpers), so this directory only
contains the process entrypoint.

## Running locally

Uses the same virtualenv as `apps/api` (see `apps/api/README.md` to create it):

```
apps/api/.venv/Scripts/python workers/run.py
```

Requires the same `.env` as the API (`DATABASE_URL`, `REDIS_URL` at minimum).

## Writing a new job handler

Every handler's sync RQ entrypoint (the `def run(...)` RQ actually calls)
must go through `app.modules.jobs.async_entrypoint.run_job_sync()`, not a
bare `asyncio.run(...)`:

```python
def run(job_id: str, tenant_id: str, ...) -> None:
    run_job_sync(_run(job_id, tenant_id, ...))
```

`asyncio.run()` alone works for a worker's *first* job and then breaks on the
second with `RuntimeError: Event loop is closed` — `app.core.db.engine` is a
process-wide singleton whose connection pool gets bound to whatever event
loop opens the first connection, but RQ hands each job a fresh loop.
`run_job_sync` disposes the pool at the end of the same job's loop so the
next job starts clean. Found the hard way in Fase 2, running a real job
through a real worker for the first time — every earlier test had called
handlers' `_run()` directly, bypassing the queue (and this bug) entirely.

Also see the platform note in `run.py` about `SimpleWorker` vs `Worker` on
Windows (`os.fork()` doesn't exist there) — not something a new handler needs
to worry about, just context for why the worker process is built the way it
is.

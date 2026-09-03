import asyncio
from collections.abc import Coroutine
from typing import Any

from app.core.db import engine


def run_job_sync(coro: Coroutine[Any, Any, None]) -> None:
    """Every job handler's sync RQ entrypoint should call this instead of
    `asyncio.run(coro)` directly.

    `app.core.db.engine` is a process-wide singleton whose pooled asyncpg
    connections are bound to whichever event loop opened them. RQ invokes
    each job's sync entrypoint through a fresh `asyncio.run()` — a new event
    loop every time — so without disposing the pool at the end of each job's
    loop, the worker's *next* job reuses a connection tied to a now-closed
    loop and crashes with `RuntimeError: Event loop is closed` deep in
    asyncpg's connection cleanup. Confirmed running a real job through a real
    RQ worker in Fase 2 — the first job in a fresh worker process works fine,
    the second one didn't, until this fix.
    """

    async def _wrapper() -> None:
        try:
            await coro
        finally:
            await engine.dispose()

    asyncio.run(_wrapper())

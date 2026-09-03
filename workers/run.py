"""RQ worker process entrypoint.

Runs in the same Python environment as apps/api (see workers/README.md) — job
handlers live inside app.modules.*.handlers so they share the domain code
(models, RLS-aware DB session helpers) with the API instead of duplicating it.
"""

import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from rq import SimpleWorker, Worker  # noqa: E402

# Must import before any job runs: a handler's own import chain doesn't
# necessarily pull in every model (e.g. nothing in the discovery job's chain
# imports Tenant, even though Job.tenant_id has a string FK to "tenants.id")
# — see model_registry's docstring for the NoReferencedTableError this
# caused in Fase 2.
from app.core import model_registry  # noqa: E402,F401
from app.core.logging import configure_logging  # noqa: E402
from app.modules.jobs.queue import get_redis_connection  # noqa: E402

if __name__ == "__main__":
    configure_logging()

    # RQ's default Worker forks a child process per job (os.fork()) — which
    # doesn't exist on Windows. Confirmed the hard way: AttributeError on the
    # very first job actually run through a real queued worker in Fase 2 (all
    # earlier testing called job handlers directly, bypassing the real queue,
    # which is exactly how this went unnoticed since Fase 0). SimpleWorker
    # runs jobs in-process instead — RQ's own documented workaround. A job
    # that crashes hard there takes the worker down with it (no child process
    # to isolate the failure), which is an acceptable trade for local/Windows
    # dev; a Linux deploy target gets the real forking Worker back for free.
    worker_class = SimpleWorker if platform.system() == "Windows" else Worker
    worker = worker_class(["default"], connection=get_redis_connection())
    worker.work()

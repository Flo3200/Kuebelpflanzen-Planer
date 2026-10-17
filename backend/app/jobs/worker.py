"""Worker process: `python -m app.jobs.worker`.

Claims jobs one at a time and enqueues periodic jobs (retention, model fitting, invoices).
Several workers can run in parallel thanks to SKIP LOCKED.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import system_session
from app.jobs.queue import claim_next, enqueue, run_job
from app.models.core import Job, Tenant

log = logging.getLogger("kp.worker")
_stop = threading.Event()

# kind -> function(now) -> period key or None (None = not due)
PERIODIC: dict[str, callable] = {}


def periodic(kind: str):
    def deco(fn):
        PERIODIC[kind] = fn
        return fn

    return deco


def load_handlers() -> None:
    """Import modules that register job handlers and periodic tasks."""
    import importlib

    for mod in (
        "app.jobs.builtin",
        "app.ai.jobs",
        "app.timemodel.jobs",
        "app.planning.jobs",
        "app.learning.jobs",
        "app.billing.jobs",
        "app.pdf.jobs",
    ):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            if exc.name != mod:
                raise


def schedule_periodic(now: datetime | None = None) -> int:
    """Enqueue periodic jobs whose period key has no job yet. Returns number enqueued."""
    now = now or datetime.now(UTC)
    created = 0
    with system_session() as db:
        tenants = list(
            db.scalars(select(Tenant.id).where(Tenant.deleted_at.is_(None), Tenant.status == "active"))
        )
        for kind, due in PERIODIC.items():
            for tenant_id in [None, *tenants]:
                key = due(db, tenant_id, now)
                if key is None:
                    continue
                exists = db.scalar(
                    select(Job.id).where(
                        Job.kind == kind,
                        Job.tenant_id.is_(None) if tenant_id is None else Job.tenant_id == tenant_id,
                        Job.payload["period"].astext == key,
                    )
                )
                if exists is None:
                    enqueue(db, kind, {"period": key, "periodic": True}, tenant_id=tenant_id)
                    created += 1
    return created


def loop(poll_seconds: float = 1.0, schedule_every: float = 60.0) -> None:
    load_handlers()
    last_schedule = 0.0
    log.info("worker started")
    while not _stop.is_set():
        if time.monotonic() - last_schedule > schedule_every:
            try:
                schedule_periodic()
            except Exception:  # noqa: BLE001
                log.exception("periodic scheduling failed")
            last_schedule = time.monotonic()
        try:
            job_id = claim_next()
        except Exception:  # noqa: BLE001 - database may be restarting
            log.exception("claim failed")
            _stop.wait(5)
            continue
        if job_id is None:
            _stop.wait(poll_seconds)
            continue
        run_job(job_id)


def start_embedded() -> threading.Thread:
    """Run the worker as a daemon thread inside the API process (development convenience)."""
    thread = threading.Thread(target=loop, name="kp-worker", daemon=True)
    thread.start()
    return thread


def stop() -> None:
    _stop.set()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    loop()


if __name__ == "__main__":
    main()

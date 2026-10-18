"""Job queue on PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED) – no extra service needed."""

from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import Actor, system_actor
from app.core.db import SYSTEM, RlsContext, session_scope, system_session
from app.core.errors import AppError
from app.i18n import t
from app.models.core import Job

log = logging.getLogger("kp.jobs")


class JobCancelled(Exception):
    pass


@dataclass
class JobContext:
    job_id: uuid.UUID
    tenant_id: uuid.UUID | None
    payload: dict[str, Any]
    db: Session
    actor: Actor

    def progress(self, fraction: float, message: str | None = None) -> None:
        with system_session() as s:
            job = s.get(Job, self.job_id)
            if job is None:
                return
            job.progress = max(0.0, min(1.0, fraction))
            if message is not None:
                job.message = message
            if job.cancel_requested:
                raise JobCancelled()

    def cancelled(self) -> bool:
        with system_session() as s:
            job = s.get(Job, self.job_id)
            return bool(job and job.cancel_requested)


Handler = Callable[[JobContext], dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    tenant_id: uuid.UUID | None,
    created_by: uuid.UUID | None = None,
    max_attempts: int = 1,
    run_after: datetime | None = None,
) -> Job:
    job = Job(
        tenant_id=tenant_id,
        kind=kind,
        payload=payload or {},
        created_by=created_by,
        max_attempts=max_attempts,
        status="queued",
    )
    if run_after is not None:
        job.run_after = run_after
    db.add(job)
    db.flush()
    return job


CLAIM_SQL = text(
    """
    UPDATE jobs SET status = 'running', started_at = now(), attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_after <= now()
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id
    """
)


def claim_next() -> uuid.UUID | None:
    with system_session() as db:
        return db.execute(CLAIM_SQL).scalar()


def run_job(job_id: uuid.UUID) -> None:
    """Execute a claimed (status running) job and store the outcome."""
    with system_session() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        kind, tenant_id, payload = job.kind, job.tenant_id, dict(job.payload or {})
        attempts, max_attempts = job.attempts, job.max_attempts
    fn = HANDLERS.get(kind)
    status, result, error = "done", None, None
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {kind!r}")
        ctx_rls = RlsContext(tenant_id=tenant_id) if tenant_id else SYSTEM
        with session_scope(ctx_rls) as db:
            ctx = JobContext(job_id, tenant_id, payload, db, system_actor(tenant_id, label=f"Job {kind}"))
            result = fn(ctx) or {}
    except JobCancelled:
        status = "cancelled"
    except AppError as exc:
        # expected, explained failure (e.g. too few measurements): German text, no retry
        log.info("job %s (%s) stopped: %s", job_id, kind, exc.code)
        error = t(exc.code, **exc.params)
        status = "failed"
    except Exception as exc:  # noqa: BLE001 - every failure is stored on the job
        log.exception("job %s (%s) failed", job_id, kind)
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=8)}"
        status = "queued" if attempts < max_attempts else "failed"
    with system_session() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        if status == "queued":
            job.run_after = datetime.now(UTC) + timedelta(seconds=30 * attempts)
        else:
            job.finished_at = datetime.now(UTC)
            job.result = result
            if status == "done":
                job.progress = 1.0


def run_pending(limit: int = 100) -> int:
    """Process queued jobs synchronously (tests, embedded mode). Returns number of jobs run."""
    count = 0
    while count < limit:
        job_id = claim_next()
        if job_id is None:
            break
        run_job(job_id)
        count += 1
    return count


def run_now(db: Session, job: Job) -> Job:
    """Commit, claim this specific job and run it inline; returns the refreshed job."""
    db.commit()
    with system_session() as s:
        claimed = s.execute(
            text(
                "UPDATE jobs SET status='running', started_at=now(), attempts=attempts+1 "
                "WHERE id = :id AND status='queued' RETURNING id"
            ),
            {"id": job.id},
        ).scalar()
    if claimed:
        run_job(job.id)
    db.expire_all()
    refreshed = db.get(Job, job.id)
    assert refreshed is not None
    return refreshed

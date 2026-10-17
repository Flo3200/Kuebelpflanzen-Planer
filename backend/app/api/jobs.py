"""Background jobs: progress, results, cancellation."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.core.errors import NotFound
from app.models.core import Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def job_dict(job: Job, with_result: bool = True) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": (job.error or "").split("\n")[0] if job.error else None,
        "payload": job.payload,
        "result": job.result if with_result else None,
        "attempts": job.attempts,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@router.get("")
def list_jobs(
    actor: CurrentActor,
    db: DB,
    kind: str | None = None,
    status: str | None = None,
    limit: int = Query(50, le=500),
) -> list[dict[str, Any]]:
    stmt = select(Job)
    if actor.tenant_id is not None:
        stmt = stmt.where(Job.tenant_id == actor.tenant_id)
    else:
        actor.require("platform.system")
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if status:
        stmt = stmt.where(Job.status == status)
    return [
        job_dict(j, with_result=False) for j in db.scalars(stmt.order_by(Job.created_at.desc()).limit(limit))
    ]


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or (actor.tenant_id is not None and job.tenant_id != actor.tenant_id):
        raise NotFound()
    data = job_dict(job)
    if actor.is_platform_admin:
        data["error_detail"] = job.error
    return data


@router.post("/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None or (actor.tenant_id is not None and job.tenant_id != actor.tenant_id):
        raise NotFound()
    if job.status == "queued":
        job.status = "cancelled"
    elif job.status == "running":
        job.cancel_requested = True
    return job_dict(job)

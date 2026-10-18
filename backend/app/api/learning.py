"""Model fitting: start (job), list, details with quality report, adopt or discard; synthetic data for demos."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.errors import Forbidden
from app.jobs.queue import enqueue, run_now
from app.learning.service import adopt, discard, fit_summary, get_fit
from app.models.core import Tenant
from app.models.field import Measurement
from app.models.formulas import ModelFit

router = APIRouter(prefix="/api/learning", tags=["learning"])


class FitIn(BaseModel):
    tier: int | None = Field(default=None, ge=1, le=9)
    sync: bool = False


@router.post("/fits", status_code=201)
def start_fit(data: FitIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("model.fit")
    tid = actor.require_tenant()
    job = enqueue(
        db,
        "learning.fit",
        {"tenant_id": str(tid), "tier": data.tier},
        tenant_id=tid,
        created_by=actor.user_id,
    )
    audit.record(
        db, actor, tenant_id=tid, entity="model_fit", entity_id=None, action="start", new={"tier": data.tier}
    )
    if data.sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result, "error": job.error}


@router.get("/fits")
def list_fits(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("planning.read")
    rows = db.scalars(
        select(ModelFit)
        .where(ModelFit.tenant_id == actor.tenant_id)
        .order_by(ModelFit.created_at.desc())
        .limit(50)
    )
    return [fit_summary(f) for f in rows]


@router.get("/fits/{fit_id}")
def fit_detail(fit_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.read")
    return fit_summary(get_fit(db, actor, fit_id), with_report=True)


class AdoptIn(BaseModel):
    parameters: bool = True
    staff: bool = True
    sigma: bool = True


@router.post("/fits/{fit_id}/adopt")
def adopt_fit(fit_id: uuid.UUID, data: AdoptIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("model.fit", "formulas.write")
    fit = adopt(db, actor, get_fit(db, actor, fit_id), data.parameters, data.staff, data.sigma)
    return fit_summary(fit)


@router.post("/fits/{fit_id}/discard")
def discard_fit(fit_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("model.fit")
    return fit_summary(discard(db, actor, get_fit(db, actor, fit_id)))


class SyntheticIn(BaseModel):
    n: int = Field(default=120, ge=10, le=2000)
    noise_sigma: float = Field(default=0.12, ge=0, le=1)
    outlier_share: float = Field(default=0.03, ge=0, le=0.3)
    seed: int = 1
    replace: bool = True
    true_params: dict[str, float] | None = None


@router.post("/synthetic")
def synthetic(data: SyntheticIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Synthetic measurements - only for demo tenants (never mixed into real data)."""
    actor.require("model.fit")
    tenant = db.get(Tenant, actor.require_tenant())
    if tenant is None or not tenant.is_demo:
        raise Forbidden("errors.demo_only")
    from app.demo.measurements import DEMO_TRUE_PARAMS
    from app.learning.synthetic import generate

    if data.replace:
        db.execute(
            delete(Measurement).where(Measurement.tenant_id == tenant.id, Measurement.source == "synthetic")
        )
    out = generate(
        db,
        tenant.id,
        n=data.n,
        noise_sigma=data.noise_sigma,
        outlier_share=data.outlier_share,
        seed=data.seed,
        true_params=data.true_params if data.true_params is not None else DEMO_TRUE_PARAMS,
    )
    audit.record(
        db,
        actor,
        tenant_id=tenant.id,
        entity="measurement",
        entity_id=None,
        action="synthetic",
        new={"n": out["created"]},
    )
    return out

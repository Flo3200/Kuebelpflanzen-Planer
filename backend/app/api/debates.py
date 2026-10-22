"""AI discussion about formulas: two models (e.g. ChatGPT and Claude) discuss in turns, the proposal is
checked against the measurements and can be adopted as a new formula version."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.core.errors import AppError, NotFound
from app.formula.debate import adopt
from app.jobs.queue import enqueue, run_now
from app.models.ai import AIModel, AIProvider
from app.models.formulas import FormulaDebate

router = APIRouter(prefix="/api/formula-debates", tags=["formulas"])


def debate_dict(d: FormulaDebate, db) -> dict[str, Any]:
    labels = {
        m.id: m.label
        for m in db.scalars(
            select(AIModel).where(AIModel.id.in_([x for x in (d.model_a_id, d.model_b_id) if x]))
        )
    }
    return {
        "id": d.id,
        "formula_key": d.formula_key,
        "question": d.question,
        "model_a": labels.get(d.model_a_id),
        "model_b": labels.get(d.model_b_id),
        "n_rounds": d.n_rounds,
        "status": d.status,
        "rounds": d.rounds,
        "proposal": d.proposal,
        "evaluation": d.evaluation,
        "error": d.error,
        "job_id": d.job_id,
        "adopted_version_id": d.adopted_version_id,
        "created_at": d.created_at,
    }


def _perm(actor) -> None:
    actor.require("formulas.write")
    actor.require("ai.use") if actor.tenant_id else actor.require("platform.formulas")


@router.get("/models")
def models(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    """Models that can take part (active models of active providers)."""
    _perm(actor)
    from app.ai.service import api_key_for
    from app.settings.service import SettingsResolver

    resolver = SettingsResolver(db, actor.tenant_id)
    providers = {p.id: p for p in db.scalars(select(AIProvider).where(AIProvider.active.is_(True)))}
    ready = {
        pid: p.kind == "fake" or bool(api_key_for(db, actor.tenant_id, resolver, p)[0])
        for pid, p in providers.items()
    }
    return [
        {
            "id": m.id,
            "label": m.label,
            "provider": providers[m.provider_id].name,
            "kind": providers[m.provider_id].kind,
            "ready": ready[m.provider_id],  # a key is there (or it is the test model)
        }
        for m in db.scalars(select(AIModel).where(AIModel.active.is_(True)).order_by(AIModel.label))
        # chat models only (image and speech models cannot discuss)
        if m.provider_id in providers and m.supports_tools
    ]


@router.get("")
def list_debates(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    _perm(actor)
    q = select(FormulaDebate).order_by(FormulaDebate.created_at.desc()).limit(30)
    q = (
        q.where(FormulaDebate.tenant_id == actor.tenant_id)
        if actor.tenant_id
        else q.where(FormulaDebate.tenant_id.is_(None))
    )
    return [debate_dict(d, db) for d in db.scalars(q)]


class DebateIn(BaseModel):
    formula_key: str = Field(default="time", pattern="^(time|unload)$")
    model_a_id: uuid.UUID | None = None
    model_b_id: uuid.UUID | None = None
    n_rounds: int = Field(default=2, ge=1, le=4)
    question: str | None = Field(default=None, max_length=2000)
    sync: bool = False


@router.post("", status_code=201)
def start(data: DebateIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    for mid in (data.model_a_id, data.model_b_id):
        if mid is not None and db.get(AIModel, mid) is None:
            raise AppError("errors.validation")
    d = FormulaDebate(
        tenant_id=actor.tenant_id,
        formula_key=data.formula_key,
        question=data.question,
        model_a_id=data.model_a_id,
        model_b_id=data.model_b_id,
        n_rounds=data.n_rounds,
        status="new",
        rounds=[],
        proposal={},
        evaluation={},
        created_by=actor.user_id,
    )
    db.add(d)
    db.flush()
    job = enqueue(
        db, "ai.formula_debate", {"debate_id": str(d.id)}, tenant_id=actor.tenant_id, created_by=actor.user_id
    )
    d.job_id = job.id
    if data.sync:
        run_now(db, job)
        db.refresh(d)
    return debate_dict(d, db)


def _get(db, actor, debate_id: uuid.UUID) -> FormulaDebate:
    d = db.get(FormulaDebate, debate_id)
    if d is None or d.tenant_id != actor.tenant_id:
        raise NotFound()
    return d


@router.get("/{debate_id}")
def get_debate(debate_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    return debate_dict(_get(db, actor, debate_id), db)


@router.post("/{debate_id}/adopt")
def adopt_proposal(debate_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """New, activated formula version from the proposal (undo: activate the previous version)."""
    _perm(actor)
    d = _get(db, actor, debate_id)
    v = adopt(db, actor, d)
    return {"version_id": v.id, "version": v.version, "debate": debate_dict(d, db)}

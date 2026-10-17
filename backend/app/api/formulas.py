"""Formula editor API: versions, tiers, validation, test evaluation, tenant overrides."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.formula.defaults import VARIABLES
from app.formula.parser import AGGREGATES, FUNCTIONS, FormulaError
from app.formula.store import compile_version, validate_expressions
from app.i18n import catalog
from app.models.formulas import Formula, FormulaVersion, ModelFit
from app.models.orders import PickupOrder
from app.timemodel.service import schedule_refresh

router = APIRouter(prefix="/api/formulas", tags=["formulas"])


def _perm(actor: Actor) -> None:
    actor.require("platform.formulas" if actor.tenant_id is None else "formulas.write")


def version_dict(v: FormulaVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "version": v.version,
        "expressions": v.expressions,
        "parameters": v.parameters,
        "note": v.note,
        "source": v.source,
        "fit_id": v.fit_id,
        "created_at": v.created_at,
        "tenant_id": v.tenant_id,
    }


def formula_dict(db: Session, f: Formula) -> dict[str, Any]:
    versions = list(
        db.scalars(
            select(FormulaVersion)
            .where(FormulaVersion.formula_id == f.id)
            .order_by(FormulaVersion.version.desc())
        )
    )
    return {
        "id": f.id,
        "key": f.key,
        "tier": f.tier,
        "name": f.name,
        "description": f.description,
        "tenant_id": f.tenant_id,
        "is_global": f.tenant_id is None,
        "overrides_id": f.overrides_id,
        "active_version_id": f.active_version_id,
        "versions": [version_dict(v) for v in versions],
    }


def variables_doc(key: str) -> list[dict[str, Any]]:
    labels = catalog().get("formula_vars", {})
    return [
        {
            "name": n,
            **meta,
            "label": labels.get(n, {}).get("label", n),
            "help": labels.get(n, {}).get("help", ""),
        }
        for n, meta in VARIABLES.get(key, {}).items()
    ]


@router.get("")
def list_formulas(actor: CurrentActor, db: DB, key: str | None = None) -> dict[str, Any]:
    if actor.tenant_id is None:
        actor.require("platform.formulas")
    else:
        actor.require("orders.read")
    cond = (
        Formula.tenant_id.is_(None)
        if actor.tenant_id is None
        else or_(Formula.tenant_id.is_(None), Formula.tenant_id == actor.tenant_id)
    )
    stmt = select(Formula).where(cond)
    if key:
        stmt = stmt.where(Formula.key == key)
    rows = list(db.scalars(stmt.order_by(Formula.key, Formula.tier, Formula.tenant_id.nullsfirst())))
    overridden = {f.overrides_id for f in rows if f.tenant_id is not None}
    fits = {}
    if actor.tenant_id is not None:
        for fit in db.scalars(
            select(ModelFit).where(ModelFit.tenant_id == actor.tenant_id).order_by(ModelFit.created_at.desc())
        ):
            fits.setdefault(
                fit.formula_id,
                {"id": fit.id, "status": fit.status, "metrics": fit.metrics, "created_at": fit.created_at},
            )
    out = []
    for f in rows:
        d = formula_dict(db, f)
        d["overridden_by_tenant"] = f.id in overridden
        d["latest_fit"] = fits.get(f.id)
        out.append(d)
    return {
        "formulas": out,
        "variables": {k: variables_doc(k) for k in VARIABLES},
        "functions": sorted(FUNCTIONS) + sorted(AGGREGATES),
    }


class VersionIn(BaseModel):
    expressions: list[dict[str, Any]]
    parameters: dict[str, Any] = {}
    note: str | None = None
    activate: bool = True


def _get_formula(db: Session, actor: Actor, formula_id: uuid.UUID) -> Formula:
    f = db.get(Formula, formula_id)
    if f is None or (f.tenant_id is not None and f.tenant_id != actor.tenant_id):
        raise NotFound()
    return f


def _tenant_copy(db: Session, actor: Actor, glob: Formula) -> Formula:
    """A tenant editing a global formula gets its own override (same key and tier)."""
    own = db.scalar(
        select(Formula).where(
            Formula.tenant_id == actor.tenant_id, Formula.key == glob.key, Formula.tier == glob.tier
        )
    )
    if own is None:
        own = Formula(
            tenant_id=actor.tenant_id,
            key=glob.key,
            tier=glob.tier,
            name=glob.name,
            description=glob.description,
            overrides_id=glob.id,
        )
        db.add(own)
        db.flush()
    return own


def create_version(
    db: Session,
    actor: Actor,
    f: Formula,
    data: VersionIn,
    source: str = "manual",
    fit_id: uuid.UUID | None = None,
) -> FormulaVersion:
    problems = validate_expressions(f.key, data.expressions, data.parameters)
    if problems:
        first = problems[0]
        raise AppError(
            "errors.formula_syntax",
            pos=first.get("pos", "–"),
            detail=f"{first['expression']}: {first['detail']}",
        )
    if f.tenant_id is None and actor.tenant_id is not None:
        f = _tenant_copy(db, actor, f)
    latest = db.scalar(select(func.max(FormulaVersion.version)).where(FormulaVersion.formula_id == f.id)) or 0
    v = FormulaVersion(
        tenant_id=f.tenant_id,
        formula_id=f.id,
        version=latest + 1,
        expressions=data.expressions,
        parameters=data.parameters,
        note=data.note,
        source=source,
        fit_id=fit_id,
        created_by=actor.user_id,
    )
    db.add(v)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=f.tenant_id,
        entity="formula",
        entity_id=f.id,
        action="version",
        new={"version": v.version, "note": data.note},
    )
    if data.activate:
        _activate(db, actor, f, v)
    return v


def _activate(db: Session, actor: Actor, f: Formula, v: FormulaVersion) -> None:
    old = f.active_version_id
    f.active_version_id = v.id
    audit.record(
        db,
        actor,
        tenant_id=f.tenant_id,
        entity="formula",
        entity_id=f.id,
        action="activate",
        old={"version_id": str(old) if old else None},
        new={"version_id": str(v.id), "version": v.version},
    )
    db.flush()
    schedule_refresh(db, f.tenant_id)


@router.post("/{formula_id}/versions", status_code=201)
def new_version(formula_id: uuid.UUID, data: VersionIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    f = _get_formula(db, actor, formula_id)
    v = create_version(db, actor, f, data)
    return {"formula": formula_dict(db, db.get(Formula, v.formula_id)), "version": version_dict(v)}


@router.post("/{formula_id}/activate/{version_id}")
def activate(formula_id: uuid.UUID, version_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    f = _get_formula(db, actor, formula_id)
    if f.tenant_id != actor.tenant_id:
        raise NotFound()
    v = db.get(FormulaVersion, version_id)
    if v is None or v.formula_id != f.id:
        raise NotFound()
    _activate(db, actor, f, v)
    return formula_dict(db, f)


@router.delete("/{formula_id}")
def reset_override(formula_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Remove a tenant's override: the global formula applies again."""
    _perm(actor)
    f = _get_formula(db, actor, formula_id)
    if f.tenant_id is None:
        raise AppError("errors.validation")
    audit.record(db, actor, tenant_id=f.tenant_id, entity="formula", entity_id=f.id, action="reset")
    db.delete(f)
    db.flush()
    schedule_refresh(db, actor.tenant_id)
    return {"ok": True}


class TestIn(BaseModel):
    key: str = "time"
    expressions: list[dict[str, Any]]
    parameters: dict[str, Any] = {}
    order_id: uuid.UUID | None = None


@router.post("/test")
def test_formula(data: TestIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Check a formula and evaluate it for one order (or a sample stop) without saving."""
    problems = validate_expressions(data.key, data.expressions, data.parameters)
    if problems:
        return {"ok": False, "problems": problems}
    fake_formula = Formula(key=data.key, tier=0, name="Test")
    version = FormulaVersion(version=0, expressions=data.expressions, parameters=data.parameters)
    try:
        cf = compile_version(fake_formula, version)
    except FormulaError as exc:
        return {
            "ok": False,
            "problems": [{"expression": "?", "code": exc.code, "detail": exc.detail, "pos": exc.pos}],
        }
    if actor.tenant_id is None:
        return {"ok": True, "problems": [], "result": None}
    from app.timemodel.estimate import Estimator

    order = (
        db.get(PickupOrder, data.order_id)
        if data.order_id
        else db.scalar(
            select(PickupOrder)
            .where(PickupOrder.tenant_id == actor.tenant_id, PickupOrder.deleted_at.is_(None))
            .limit(1)
        )
    )
    if order is None or order.tenant_id != actor.tenant_id:
        return {"ok": True, "problems": [], "result": None}
    try:
        if data.key == "time":
            est = Estimator(db, actor.tenant_id, time_formula=cf)
            result = est.order_estimate(order)
            out = {
                k: result.get(k)
                for k in (
                    "team_size",
                    "duration_min",
                    "labour_min",
                    "planning_duration_min",
                    "durations_by_team",
                    "plants",
                    "error",
                )
            }
        else:
            est = Estimator(db, actor.tenant_id)
            est.price_formula = cf
            result = est.order_estimate(order)
            out = {"price": result.get("price"), "labour_min": result.get("labour_min")}
    except FormulaError as exc:
        return {
            "ok": False,
            "problems": [{"expression": "?", "code": exc.code, "detail": exc.detail, "pos": exc.pos}],
        }
    return {"ok": True, "problems": [], "order_number": order.number, "result": out}

"""Fitting the formula "unload" to measured unloading times (package F).

Like the time formula (D17): robust loss (Huber), regularisation towards the current values, only as
many parameters as the measurements carry (learning.min_measurements_per_param each, in the order of
the formula's learnable parameters). The result is a proposal; adopting it creates a new formula
version (source "fit"), undoable like every formula version.
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.errors import AppError
from app.formula.store import find_formula, load_active
from app.models.field import UnloadMeasurement
from app.settings.service import SettingsResolver

MIN_MEASUREMENTS = 5


def _rows(db: Session, tenant_id: uuid.UUID) -> list[UnloadMeasurement]:
    return list(
        db.scalars(
            select(UnloadMeasurement)
            .where(UnloadMeasurement.tenant_id == tenant_id, UnloadMeasurement.excluded.is_(False))
            .order_by(UnloadMeasurement.date)
        )
    )


def _predict(cf, m: UnloadMeasurement, params: dict[str, float]) -> float:
    weights = [float(w) for w in (m.weights or [])] or [m.total_weight / max(1, m.n_plants)] * m.n_plants
    out = cf.run(
        {
            "n_plants": m.n_plants,
            "total_weight": m.total_weight,
            "max_weight": max(weights, default=0),
            "team": max(1, m.team_size),
            "n_stops": max(1, m.n_stops),
        },
        [{"weight": w, "height": 0.0} for w in weights],
        params,
    )
    return float(out["unload"])


def proposal(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    r = SettingsResolver(db, tenant_id)
    cf = load_active(db, tenant_id, "unload", 1)
    rows = _rows(db, tenant_id)
    spec = cf.version.parameters or {}
    learnable = [k for k, v in spec.items() if v.get("learnable")]
    base = dict(cf.params)
    out: dict[str, Any] = {
        "n": len(rows),
        "formula": {"name": cf.formula.name, "version": cf.version.version},
        "parameters": {k: {"current": base[k], "unit": spec[k].get("unit")} for k in spec},
        "proposed": None,
    }
    if len(rows) < MIN_MEASUREMENTS or not learnable:
        out["reason"] = "too_few"
        out["min"] = MIN_MEASUREMENTS
        return out
    per_param = max(1, int(r.get("learning.min_measurements_per_param")))
    k = max(1, min(len(learnable), len(rows) // per_param))
    fit_names = learnable[:k]
    y = np.array([m.minutes for m in rows], dtype=float)
    lam = float(r.get("learning.lambda"))
    delta = float(r.get("learning.huber_delta_min"))
    scale = np.array([float(spec[n].get("scale") or 1.0) for n in fit_names])
    lo = np.array([float(spec[n].get("min", -np.inf)) for n in fit_names])
    hi = np.array([float(spec[n].get("max", np.inf)) for n in fit_names])
    x0 = np.clip(np.array([base[n] for n in fit_names]), lo, hi)

    def params_of(x: np.ndarray) -> dict[str, float]:
        return {**base, **{n: float(v) for n, v in zip(fit_names, x, strict=True)}}

    def residuals(x: np.ndarray) -> np.ndarray:
        pred = np.array([_predict(cf, m, params_of(x)) for m in rows])
        reg = np.sqrt(lam) * (x - x0) / scale
        return np.concatenate([pred - y, reg])

    res = least_squares(residuals, x0, bounds=(lo, hi), loss="huber", f_scale=delta)
    after = params_of(res.x)
    before_pred = np.array([_predict(cf, m, base) for m in rows])
    after_pred = np.array([_predict(cf, m, after) for m in rows])
    out["proposed"] = {n: round(float(after[n]), 4) for n in fit_names}
    out["fitted"] = fit_names
    out["mae_before"] = round(float(np.mean(np.abs(before_pred - y))), 2)
    out["mae_after"] = round(float(np.mean(np.abs(after_pred - y))), 2)
    out["points"] = [
        {"measured": round(float(a), 1), "before": round(float(b), 1), "after": round(float(c), 1)}
        for a, b, c in zip(y, before_pred, after_pred, strict=True)
    ]
    return out


def adopt(db: Session, actor: Actor) -> dict[str, Any]:
    from app.api.formulas import VersionIn, create_version

    tid = actor.require_tenant()
    p = proposal(db, tid)
    if not p.get("proposed"):
        raise AppError("errors.unload_fit_too_few", n=p["n"], min=MIN_MEASUREMENTS)
    cf = load_active(db, tid, "unload", 1)
    params = {k: dict(v) for k, v in (cf.version.parameters or {}).items()}
    for k, v in p["proposed"].items():
        params[k]["value"] = v
    note = f"Anpassung an {p['n']} Ablade-Messungen (Fehler {p['mae_before']} → {p['mae_after']} min)"
    v = create_version(
        db,
        actor,
        find_formula(db, tid, "unload", 1),
        VersionIn(expressions=cf.version.expressions, parameters=params, note=note[:300], activate=True),
        source="fit",
    )
    from app.timemodel.service import schedule_refresh

    schedule_refresh(db, tid)
    return {**p, "adopted_version": v.version}

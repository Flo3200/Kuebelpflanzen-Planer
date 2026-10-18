"""Run a model fit (proposal), adopt it (new formula version, staff factors, planning buffer) or discard it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.formula.store import find_formula, load_active
from app.learning.fit import (
    FitConfig,
    base_params,
    coverage,
    cross_validate,
    error_metrics,
    fit_params,
    quality_report,
    sigma_from,
    team_speed,
)
from app.learning.samples import prepare_samples
from app.models.formulas import Formula, ModelFit
from app.models.masterdata import StaffMember
from app.settings.service import SettingsResolver, set_value
from app.timemodel.estimate import Estimator


def config_from(r: SettingsResolver) -> FitConfig:
    return FitConfig(
        loss=str(r.get("learning.loss")),
        huber_delta=float(r.get("learning.huber_delta_min")),
        lam=float(r.get("learning.lambda")),
        min_per_param=int(r.get("learning.min_measurements_per_param")),
        folds=int(r.get("learning.cv_folds")),
        staff_prior_n=int(r.get("learning.staff_factor_prior_n")),
    )


def available_tiers(db: Session, tenant_id: uuid.UUID) -> list[int]:
    rows = db.scalars(
        select(Formula.tier).where(
            Formula.key == "time", (Formula.tenant_id.is_(None)) | (Formula.tenant_id == tenant_id)
        )
    )
    return sorted(set(rows))


def current_staff_factors(r: SettingsResolver, staff_ids: list[str]) -> dict[str, float]:
    out = {}
    for sid in staff_ids:
        try:
            out[sid] = float(r.get("staff.carry_speed_factor", ("staff", uuid.UUID(sid))))
        except ValueError:
            continue
    return out


def run_fit(db: Session, tenant_id: uuid.UUID, tier: int | None = None, progress=None) -> ModelFit:
    progress = progress or (lambda f, m: None)
    r = SettingsResolver(db, tenant_id)
    cfg = config_from(r)
    active_tier = int(r.get("time.formula_tier"))
    target_tier = tier or active_tier
    progress(0.05, "Messungen werden vorbereitet …")
    est = Estimator(db, tenant_id)
    samples = prepare_samples(db, tenant_id, est)
    used = [s for s in samples if s.used]
    minimum = max(2 * cfg.folds, cfg.min_per_param)
    if len(used) < minimum:
        raise AppError("errors.fit_too_few", min=minimum)
    staff_ids = sorted({m for s in used for m in s.members})
    staff_now = current_staff_factors(r, staff_ids)
    tiers = available_tiers(db, tenant_id) or [1]
    cv_by_tier: dict[int, dict[str, Any]] = {}
    for i, t in enumerate(tiers):
        progress(0.1 + 0.6 * i / len(tiers), f"Kreuzvalidierung Stufe {t} …")
        formula_t = load_active(db, tenant_id, "time", t)
        cv = cross_validate(samples, formula_t, cfg, staff_now)
        cv["name"] = formula_t.formula.name
        cv["n_learnable"] = sum(
            1 for v in (formula_t.version.parameters or {}).values() if v.get("learnable")
        )
        cv_by_tier[t] = cv
    progress(0.75, "Endgültige Anpassung …")
    formula = load_active(db, tenant_id, "time", target_tier)
    out = fit_params(samples, formula, cfg)
    base = base_params(formula)
    before = {s.measurement_id: s.predict(formula, base, team_speed(s, staff_now)) for s in samples}
    after = {
        s.measurement_id: s.predict(formula, out.params, team_speed(s, {**staff_now, **out.staff}))
        for s in samples
    }
    meas = [s.measured for s in used]
    oof = cv_by_tier.get(target_tier, {}).get("oof", {})
    oof_used = [oof[s.measurement_id] for s in used if s.measurement_id in oof]
    meas_oof = [s.measured for s in used if s.measurement_id in oof]
    sigma = (
        sigma_from(oof_used, meas_oof)
        if oof_used
        else sigma_from([after[s.measurement_id] for s in used], meas)
    )
    q = float(r.get("time.planning_quantile"))
    sigma_now = float(r.get("time.error_sigma"))
    report = quality_report(samples, before, after, oof)
    # a better tier is only suggested, never switched automatically
    suggestion = None
    cur = cv_by_tier.get(active_tier, {}).get("cv", {}).get("mae")
    best = min(
        ((t, c["cv"]["mae"]) for t, c in cv_by_tier.items() if c.get("folds")),
        key=lambda x: x[1],
        default=None,
    )
    if best and cur and best[0] != active_tier and best[1] < 0.95 * cur:
        n_needed = cv_by_tier[best[0]]["n_learnable"] * cfg.min_per_param
        suggestion = {
            "tier": best[0],
            "mae": best[1],
            "mae_active": cur,
            "enough_data": len(used) >= n_needed,
        }
    meta = formula.version.parameters or {}
    names = {
        str(s.id): s.name for s in db.scalars(select(StaffMember).where(StaffMember.tenant_id == tenant_id))
    }
    fit = ModelFit(
        tenant_id=tenant_id,
        formula_id=formula.formula.id,
        base_version_id=formula.version.id,
        status="proposed",
        n_measurements=len(used),
        parameters={
            k: {
                "old": base[k],
                "new": round(out.params[k], 5),
                "se": round(out.se.get(k, float("nan")), 5) if k in out.se else None,
                "fitted": k in out.fitted,
                "unit": meta[k].get("unit", ""),
                "learnable": bool(meta[k].get("learnable")),
            }
            for k in base
        },
        staff_factors={
            m: {
                "name": names.get(m, m),
                "old": round(staff_now.get(m, 1.0), 3),
                "new": round(f, 3),
                "se": round(out.staff_se.get(m, float("nan")), 3),
                "n": out.staff_n.get(m, 0),
            }
            for m, f in out.staff.items()
        },
        metrics={
            "before": error_metrics([before[s.measurement_id] for s in used], meas),
            "after": error_metrics([after[s.measurement_id] for s in used], meas),
            "cv": {str(t): {k: v for k, v in c.items() if k != "oof"} for t, c in cv_by_tier.items()},
            "tier": target_tier,
            "active_tier": active_tier,
            "sigma": {
                "current": sigma_now,
                "proposed": sigma,
                "quantile": q,
                "coverage_current": coverage(
                    oof_used or [after[s.measurement_id] for s in used], meas_oof or meas, sigma_now, q
                ),
                "coverage_proposed": coverage(
                    oof_used or [after[s.measurement_id] for s in used], meas_oof or meas, sigma, q
                )
                if sigma
                else None,
            },
            "suggestion": suggestion,
            "loss": cfg.loss,
            "lambda": cfg.lam,
            "nfev": out.nfev,
            "converged": out.success,
            "excluded": sum(1 for s in samples if not s.used),
        },
        report=report,
    )
    db.add(fit)
    db.flush()
    progress(1.0, "Fertig")
    return fit


def fit_summary(f: ModelFit, with_report: bool = False) -> dict[str, Any]:
    d = {
        "id": f.id,
        "status": f.status,
        "created_at": f.created_at,
        "n_measurements": f.n_measurements,
        "formula_id": f.formula_id,
        "base_version_id": f.base_version_id,
        "parameters": f.parameters,
        "staff_factors": f.staff_factors,
        "metrics": f.metrics,
        "decided_at": f.decided_at,
        "new_version_id": f.new_version_id,
    }
    if with_report:
        d["report"] = f.report
    return d


def get_fit(db: Session, actor: Actor, fit_id: uuid.UUID) -> ModelFit:
    f = db.get(ModelFit, fit_id)
    if f is None or f.tenant_id != actor.tenant_id:
        raise NotFound()
    return f


def adopt(
    db: Session, actor: Actor, fit: ModelFit, parameters: bool = True, staff: bool = True, sigma: bool = True
) -> ModelFit:
    from app.api.formulas import VersionIn, create_version
    from app.models.formulas import FormulaVersion

    if fit.status != "proposed":
        raise AppError("errors.already_decided", status_code=409)
    batch = uuid.uuid4()
    if parameters:
        formula = db.get(Formula, fit.formula_id)
        base_version = db.get(FormulaVersion, fit.base_version_id)
        if formula is None or base_version is None:
            raise NotFound()
        params = {k: dict(v) for k, v in (base_version.parameters or {}).items()}
        for k, v in fit.parameters.items():
            if k in params and v.get("fitted"):
                params[k]["value"] = v["new"]
        n = fit.metrics.get("after", {})
        note = f"Anpassung an {fit.n_measurements} Messungen (Fehler {fit.metrics.get('before', {}).get('mae')} → {n.get('mae')} min)"
        own = find_formula(db, actor.tenant_id, "time", formula.tier)
        v = create_version(
            db,
            actor,
            own,
            VersionIn(
                expressions=base_version.expressions, parameters=params, note=note[:300], activate=True
            ),
            source="fit",
            fit_id=fit.id,
        )
        fit.new_version_id = v.id
    if staff:
        for sid, v in (fit.staff_factors or {}).items():
            try:
                object_id = uuid.UUID(sid)
            except ValueError:
                continue
            set_value(
                db,
                actor,
                scope="staff",
                key="staff.carry_speed_factor",
                value=round(float(v["new"]), 3),
                tenant_id=actor.tenant_id,
                object_id=object_id,
                batch_id=batch,
            )
    proposed_sigma = (fit.metrics.get("sigma") or {}).get("proposed")
    if sigma and proposed_sigma:
        set_value(
            db,
            actor,
            scope="tenant",
            key="time.error_sigma",
            value=float(proposed_sigma),
            tenant_id=actor.tenant_id,
            batch_id=batch,
        )
    fit.status = "adopted"
    fit.decided_by = actor.user_id
    fit.decided_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        tenant_id=fit.tenant_id,
        entity="model_fit",
        entity_id=fit.id,
        action="adopt",
        new={"parameters": parameters, "staff": staff, "sigma": sigma},
        batch_id=batch,
    )
    from app.timemodel.service import schedule_refresh

    schedule_refresh(db, actor.tenant_id)
    return fit


def discard(db: Session, actor: Actor, fit: ModelFit) -> ModelFit:
    if fit.status != "proposed":
        raise AppError("errors.already_decided", status_code=409)
    fit.status = "discarded"
    fit.decided_by = actor.user_id
    fit.decided_at = datetime.now(UTC)
    audit.record(db, actor, tenant_id=fit.tenant_id, entity="model_fit", entity_id=fit.id, action="discard")
    return fit

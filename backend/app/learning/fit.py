"""Fitting learnable formula parameters and personal speed factors to measurements.

Objective (spec 7.5):  sum ρ(predicted − measured) + λ · sum ((θ − θ_default) / scale)²
                       + prior_n · sum ((f_person − 1) · g_person)²
g_person is the typical effect of that person's factor on one measurement (root mean square of
∂prediction/∂f over the person's measurements), so prior_n counts as that many pseudo-measurements
at f = 1: the factor moves away from 1 only as far as the person's own measurements justify.
Personal factors are relative to the average worker: their mean is held at 1 (otherwise a common
level of all factors and the formula parameters could not be told apart).
ρ is the squared error or Huber (robust, solved by iteratively reweighted least squares, so the
robust weights only apply to measurements, never to the regularisation). Parameters are fitted
only if there are enough measurements per parameter (the most influential ones first).
k-fold cross-validation reports the error on unseen data per formula tier.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from statistics import NormalDist, median
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from app.formula.store import CompiledFormula
from app.learning.samples import Sample


@dataclass
class FitConfig:
    loss: str = "huber"
    huber_delta: float = 6.0
    lam: float = 1.0
    min_per_param: int = 15
    folds: int = 5
    staff_prior_n: int = 20
    per_plant_weight: float = 0.5
    irls_rounds: int = 4
    seed: int = 1


@dataclass
class FitOutcome:
    params: dict[str, float]
    fitted: list[str]
    se: dict[str, float]
    staff: dict[str, float]
    staff_se: dict[str, float]
    staff_n: dict[str, int]
    weights: dict[str, float] = field(default_factory=dict)  # robust weight per measurement id
    nfev: int = 0
    success: bool = True
    message: str = ""


def team_speed(s: Sample, staff: dict[str, float]) -> float:
    if not s.members:
        return 1.0
    return sum(staff.get(m, 1.0) for m in s.members) / len(s.members)


def base_params(formula: CompiledFormula) -> dict[str, float]:
    return {k: float(v.get("value", 0)) for k, v in (formula.version.parameters or {}).items()}


def choose_params(used: list[Sample], formula: CompiledFormula, cfg: FitConfig) -> list[str]:
    """All learnable parameters if there are enough measurements, else the most influential ones."""
    meta = formula.version.parameters or {}
    learn = [k for k, v in meta.items() if v.get("learnable")]
    k_max = len(used) // max(1, cfg.min_per_param)
    if k_max >= len(learn):
        return learn
    if k_max <= 0:
        return []
    base = base_params(formula)
    base_pred = [s.predict(formula, base) for s in used]
    sens = {}
    for k in learn:
        step = float(meta[k].get("scale") or abs(base[k]) or 1.0)
        prm = {**base, k: base[k] + step}
        sens[k] = sum(abs(s.predict(formula, prm) - b) for s, b in zip(used, base_pred, strict=True)) / len(
            used
        )
    return sorted(learn, key=lambda k: -sens[k])[:k_max]


def fit_params(
    samples: list[Sample], formula: CompiledFormula, cfg: FitConfig, fit_staff: bool = True
) -> FitOutcome:
    meta = formula.version.parameters or {}
    base = base_params(formula)
    used = [s for s in samples if s.used]
    names = choose_params(used, formula, cfg)
    staff_n = Counter(m for s in used for m in s.members)
    staff_ids = sorted(staff_n) if fit_staff else []
    kp, ks = len(names), len(staff_ids)
    if not used or kp + ks == 0:
        return FitOutcome(dict(base), [], {}, {}, {}, dict(staff_n), message="nothing to fit")
    # personal factors: realistic range (half to double the average speed)
    lo = np.array([float(meta[k].get("min", -np.inf)) for k in names] + [0.5] * ks)
    hi = np.array([float(meta[k].get("max", np.inf)) for k in names] + [2.0] * ks)
    x0 = np.array([base[k] for k in names] + [1.0] * ks)
    eps = 1e-9
    x0 = np.clip(x0, lo + eps, hi - eps)
    p_scale = np.array([float(meta[k].get("scale") or max(abs(base[k]), 1e-3)) for k in names])
    x_scale = np.concatenate([p_scale, np.full(ks, 0.2)])
    base_vec = np.array([base[k] for k in names])
    # typical effect of each personal factor on one of its measurements (at the default parameters)
    g_staff = np.ones(ks)
    if ks:
        sq: dict[str, list[float]] = {m: [] for m in staff_ids}
        for s in used:
            p0 = s.predict(formula, base, 1.0)
            for m in set(s.members):
                bumped = {**{x: 1.0 for x in s.members}, m: 1.1}
                sq[m].append(((s.predict(formula, base, team_speed(s, bumped)) - p0) / 0.1) ** 2)
        g_staff = np.array([math.sqrt(sum(sq[m]) / len(sq[m])) if sq[m] else 1.0 for m in staff_ids])
    mean_anchor = float(np.mean(g_staff)) * math.sqrt(max(1, len(used))) * 10 if ks else 0.0
    pp_rows = [(i, idx, minutes) for i, s in enumerate(used) for idx, minutes in s.per_plant]
    staff_index = {m: j for j, m in enumerate(staff_ids)}
    n_data = len(used) + len(pp_rows)
    w = np.ones(n_data)

    n_rows = n_data + kp + ks + (1 if ks else 0)
    sparsity = lil_matrix((n_rows, kp + ks), dtype=int)
    for i, s in enumerate(used):
        sparsity[i, :kp] = 1
        for m in s.members:
            if m in staff_index:
                sparsity[i, kp + staff_index[m]] = 1
    for r, (i, _idx, _m) in enumerate(pp_rows):
        sparsity[len(used) + r, :kp] = 1
        for m in used[i].members:
            if m in staff_index:
                sparsity[len(used) + r, kp + staff_index[m]] = 1
    for j in range(kp + ks):
        sparsity[n_data + j, j] = 1
    if ks:
        sparsity[n_rows - 1, kp:] = 1

    def raw_residuals(x: np.ndarray) -> np.ndarray:
        prm = {**base, **dict(zip(names, x[:kp], strict=True))}
        staff = dict(zip(staff_ids, x[kp:], strict=True))
        out = np.empty(n_data)
        works: dict[int, list[float]] = {}
        for i, s in enumerate(used):
            out[i] = s.predict(formula, prm, team_speed(s, staff)) - s.measured
        for r, (i, idx, minutes) in enumerate(pp_rows):
            s = used[i]
            if i not in works:
                works[i] = s.plant_work(formula, prm, team_speed(s, staff))
            out[len(used) + r] = (
                works[i][idx] / max(1, s.team) / team_speed(s, staff) - minutes
            ) * math.sqrt(cfg.per_plant_weight)
        return out

    def residuals(x: np.ndarray) -> np.ndarray:
        data = raw_residuals(x) * np.sqrt(w)
        reg_p = math.sqrt(cfg.lam) * (x[:kp] - base_vec) / p_scale
        reg_s = math.sqrt(cfg.staff_prior_n) * (x[kp:] - 1.0) * g_staff
        mean_one = [(float(np.mean(x[kp:])) - 1.0) * mean_anchor] if ks else []
        return np.concatenate([data, reg_p, reg_s, mean_one])

    x = x0
    nfev = 0
    res = None
    if cfg.loss == "huber":
        # robust from the start (built-in Huber loss), so a few outliers cannot pull the fit into a
        # bad local optimum before the exact reweighting below takes over
        res = least_squares(
            residuals,
            x,
            bounds=(lo, hi),
            x_scale=x_scale,
            method="trf",
            jac_sparsity=sparsity,
            loss="huber",
            f_scale=cfg.huber_delta,
            max_nfev=200,
            xtol=1e-6,
            ftol=1e-6,
        )
        x = res.x
        nfev += res.nfev
        r = np.abs(raw_residuals(x))
        w = np.where(r <= cfg.huber_delta, 1.0, cfg.huber_delta / np.maximum(r, 1e-9))
    rounds = cfg.irls_rounds if cfg.loss == "huber" else 1
    for _ in range(rounds):
        res = least_squares(
            residuals,
            x,
            bounds=(lo, hi),
            x_scale=x_scale,
            method="trf",
            jac_sparsity=sparsity,
            max_nfev=200,
            xtol=1e-6,
            ftol=1e-6,
        )
        x = res.x
        nfev += res.nfev
        if cfg.loss != "huber":
            break
        r = np.abs(raw_residuals(x))
        new_w = np.where(r <= cfg.huber_delta, 1.0, cfg.huber_delta / np.maximum(r, 1e-9))
        if np.max(np.abs(new_w - w)) < 0.02:
            w = new_w
            break
        w = new_w
    # standard errors from the Jacobian of the final weighted problem
    se_all = np.full(kp + ks, np.nan)
    try:
        jac = res.jac.toarray() if hasattr(res.jac, "toarray") else np.asarray(res.jac)
        data_r = raw_residuals(x) * np.sqrt(w)
        dof = max(1, n_data - (kp + ks))
        s2 = float(np.sum(data_r**2)) / dof
        cov = np.linalg.pinv(jac.T @ jac) * s2
        se_all = np.sqrt(np.clip(np.diag(cov), 0, None))
    except (np.linalg.LinAlgError, ValueError):
        pass
    params = {**base, **{k: float(v) for k, v in zip(names, x[:kp], strict=True)}}
    return FitOutcome(
        params=params,
        fitted=names,
        se={k: float(se_all[j]) for j, k in enumerate(names)},
        staff={m: float(x[kp + j]) for j, m in enumerate(staff_ids)},
        staff_se={m: float(se_all[kp + j]) for j, m in enumerate(staff_ids)},
        staff_n=dict(staff_n),
        weights={s.measurement_id: float(w[i]) for i, s in enumerate(used)},
        nfev=nfev,
        success=bool(res.success) if res is not None else False,
        message=str(res.message) if res is not None else "",
    )


def error_metrics(pred: list[float], meas: list[float]) -> dict[str, float]:
    if not pred:
        return {"n": 0}
    p, m = np.array(pred), np.array(meas)
    err = p - m
    rel = np.abs(err) / np.maximum(m, 1.0)
    return {
        "n": len(pred),
        "mae": round(float(np.mean(np.abs(err))), 2),
        "rmse": round(float(np.sqrt(np.mean(err**2))), 2),
        "mape": round(float(np.mean(rel)) * 100, 1),
        "bias": round(float(np.mean(err)), 2),
    }


def cross_validate(
    samples: list[Sample],
    formula: CompiledFormula,
    cfg: FitConfig,
    current_staff: dict[str, float] | None = None,
) -> dict[str, Any]:
    """k-fold CV: fitted on k−1 folds, error on the unseen fold. Baseline = current model."""
    used = [s for s in samples if s.used]
    k = min(cfg.folds, len(used) // 2)
    if k < 2:
        return {"folds": 0}
    rng = np.random.default_rng(cfg.seed)
    order = rng.permutation(len(used))
    folds = [order[i::k] for i in range(k)]
    oof = np.zeros(len(used))
    cv_cfg = FitConfig(**{**cfg.__dict__, "irls_rounds": min(cfg.irls_rounds, 3)})
    fitted_names: set[str] = set()
    for f in range(k):
        test = set(folds[f].tolist())
        train = [s for i, s in enumerate(used) if i not in test]
        out = fit_params(train, formula, cv_cfg)
        fitted_names |= set(out.fitted)
        for i in test:
            oof[i] = used[i].predict(formula, out.params, team_speed(used[i], out.staff))
    base = base_params(formula)
    staff0 = current_staff or {}
    baseline = [s.predict(formula, base, team_speed(s, staff0)) for s in used]
    meas = [s.measured for s in used]
    return {
        "folds": k,
        "cv": error_metrics(oof.tolist(), meas),
        "baseline": error_metrics(baseline, meas),
        "fitted_params": sorted(fitted_names),
        "oof": {s.measurement_id: float(oof[i]) for i, s in enumerate(used)},
    }


def sigma_from(pred: list[float], meas: list[float]) -> float | None:
    """Robust spread of log(measured / predicted) - the lognormal error used for the planning buffer."""
    logs = [math.log(m / p) for p, m in zip(pred, meas, strict=True) if p > 0.5 and m > 0.5]
    if len(logs) < 5:
        return None
    med = median(logs)
    mad = median([abs(x - med) for x in logs])
    return round(max(0.02, 1.4826 * mad), 3)


def coverage(pred: list[float], meas: list[float], sigma: float, q: float) -> float | None:
    if not pred:
        return None
    factor = math.exp(NormalDist().inv_cdf(q) * sigma)
    return round(sum(1 for p, m in zip(pred, meas, strict=True) if m <= p * factor) / len(pred), 3)


def _bucket(feature: str, value: Any) -> str:
    if feature == "total_weight":
        return "<50" if value < 50 else "50–150" if value < 150 else "150–300" if value < 300 else "≥300"
    if feature == "path_length":
        return "<15" if value < 15 else "15–40" if value < 40 else "≥40"
    if feature == "n_plants":
        return "1" if value <= 1 else "2–3" if value <= 3 else "4–6" if value <= 6 else "≥7"
    if feature in ("stairs", "narrow", "experiment"):
        return "ja" if value else "nein"
    return str(value)


def quality_report(
    samples: list[Sample], before: dict[str, float], after: dict[str, float], oof: dict[str, float]
) -> dict[str, Any]:
    used = [s for s in samples if s.used]
    points = [
        {
            "id": s.measurement_id,
            "order": s.order_number,
            "measured": round(s.measured, 1),
            "before": round(before.get(s.measurement_id, 0.0), 1),
            "after": round(after.get(s.measurement_id, 0.0), 1),
            "oof": round(oof[s.measurement_id], 1) if s.measurement_id in oof else None,
            "team": s.team,
            "used": s.used,
            "exclude_reason": s.exclude_reason,
            "experiment": s.experiment,
            "features": s.features,
            "source": s.extra.get("source"),
        }
        for s in samples
    ]
    res_after = [after[s.measurement_id] - s.measured for s in used]
    hist: list[dict[str, float]] = []
    if res_after:
        counts, edges = np.histogram(res_after, bins=min(20, max(5, len(res_after) // 6)))
        hist = [
            {"from": round(float(edges[i]), 1), "to": round(float(edges[i + 1]), 1), "n": int(c)}
            for i, c in enumerate(counts)
        ]
    by_feature = []
    for feat in ("total_weight", "n_plants", "stairs", "path_length", "narrow", "team", "experiment"):
        groups: dict[str, list[Sample]] = {}
        for s in used:
            groups.setdefault(_bucket(feat, s.features.get(feat)), []).append(s)
        for g, ss in groups.items():
            eb = [abs(before[s.measurement_id] - s.measured) for s in ss]
            ea = [after[s.measurement_id] - s.measured for s in ss]
            by_feature.append(
                {
                    "feature": feat,
                    "group": g,
                    "n": len(ss),
                    "mae_before": round(sum(eb) / len(eb), 2),
                    "mae_after": round(sum(abs(x) for x in ea) / len(ea), 2),
                    "bias_after": round(sum(ea) / len(ea), 2),
                }
            )
    # outlier candidates: far off in relative terms (long stops naturally scatter more in minutes)
    outliers = []
    logs = [
        (s, math.log(s.measured / after[s.measurement_id]))
        for s in used
        if s.measured > 0.5 and after[s.measurement_id] > 0.5
    ]
    if len(logs) >= 8:
        med = median([x for _, x in logs])
        mad = 1.4826 * median([abs(x - med) for _, x in logs]) or 0.05
        for s, x in logs:
            r = after[s.measurement_id] - s.measured
            if abs(x - med) > 3 * mad and abs(r) > 5:
                outliers.append(
                    {
                        "id": s.measurement_id,
                        "order": s.order_number,
                        "residual": round(r, 1),
                        "ratio": round(math.exp(x), 2),
                    }
                )
    return {"points": points, "histogram": hist, "by_feature": by_feature, "outliers": outliers}

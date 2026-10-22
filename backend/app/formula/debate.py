"""AI discussion about a formula (round 2, package N): two models (e.g. ChatGPT and Claude) take turns.

Each turn gets the current formula in the app's formula language, the allowed variables and functions,
key figures of the real measurements and the transcript so far, and answers with a short argument and
optionally a complete formula. The final proposal is checked by the formula parser and evaluated on the
measurements (with its starting values and after fitting its learnable parameters). Adopting it creates
a new, revocable formula version - never automatically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai import service as ai
from app.core.errors import AppError
from app.formula.defaults import VARIABLES
from app.formula.parser import AGGREGATES, FUNCTIONS
from app.formula.store import CompiledFormula, compile_version, load_active, validate_expressions
from app.models.ai import AIModel
from app.models.formulas import FormulaDebate, FormulaVersion
from app.settings.service import SettingsResolver


def _param_spec(name: str, value: Any, old: dict[str, Any] | None) -> dict[str, Any]:
    """Parameters from a model are plain numbers; keep bounds of known ones, new ones are learnable."""
    if isinstance(value, dict):
        value = value.get("value")
    v = float(value)
    if old is not None:
        return {**old, "value": v}
    return {
        "value": v,
        "learnable": True,
        "min": 0.0,
        "max": max(10.0, abs(v) * 10),
        "unit": "",
        "scale": max(abs(v), 0.1),
    }


def normalise(formula: dict[str, Any] | None, current: FormulaVersion) -> dict[str, Any] | None:
    if not formula or not formula.get("expressions"):
        return None
    old = current.parameters or {}
    params: dict[str, Any] = {}
    for k, v in (formula.get("parameters") or {}).items():
        try:
            params[str(k)] = _param_spec(str(k), v, old.get(k))
        except (TypeError, ValueError):
            continue
    exprs = [
        {
            "name": str(e.get("name")),
            "level": "plant" if e.get("level") == "plant" else "stop",
            "expr": str(e.get("expr")),
        }
        for e in formula["expressions"]
        if e.get("name") and e.get("expr")
    ]
    # parameters the expressions still use but the model left out keep their current value
    for k, spec in old.items():
        if k not in params and any(k in e["expr"] for e in exprs):
            params[k] = spec
    return {"expressions": exprs, "parameters": params}


def _stats(db: Session, tenant_id: uuid.UUID | None, key: str, compiled: CompiledFormula) -> dict[str, Any]:
    """Error of the current formula on the measurements (only the time formula has stop measurements)."""
    if key != "time" or tenant_id is None:
        return {"n": 0}
    from app.learning.fit import error_metrics
    from app.learning.samples import prepare_samples
    from app.timemodel.estimate import Estimator

    samples = [s for s in prepare_samples(db, tenant_id, Estimator(db, tenant_id)) if s.used]
    if not samples:
        return {"n": 0}
    pred = [s.predict(compiled, compiled.params) for s in samples]
    meas = [s.measured for s in samples]
    out = error_metrics(pred, meas)
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        groups.setdefault("Treppe" if s.features["stairs"] else "ohne Treppe", []).append(i)
        groups.setdefault(f"Team {s.team}", []).append(i)
        w = s.features["total_weight"]
        groups.setdefault("schwer (>150 kg)" if w > 150 else "leicht (≤150 kg)", []).append(i)
    out["by_group"] = {
        g: {"n": len(ix), "bias": round(sum(pred[i] - meas[i] for i in ix) / len(ix), 1)}
        for g, ix in groups.items()
    }
    return out


def context_for(db: Session, tenant_id: uuid.UUID | None, key: str) -> dict[str, Any]:
    r = SettingsResolver(db, tenant_id)
    tier = int(r.get("time.formula_tier")) if key == "time" else 1
    compiled = load_active(db, tenant_id, key, tier)
    v = compiled.version
    return {
        "key": key,
        "tier": tier,
        "current": {
            "expressions": v.expressions,
            "parameters": {k: spec.get("value") for k, spec in (v.parameters or {}).items()},
        },
        "variables": {k: f"{spec['level']}, {spec['unit']}" for k, spec in VARIABLES.get(key, {}).items()},
        "functions": sorted(FUNCTIONS) + sorted(AGGREGATES),
        "stats": _stats(db, tenant_id, key, compiled),
        "_compiled": compiled,
    }


def _turn_text(ctx: dict[str, Any], question: str | None, rounds: list[dict[str, Any]], role: str) -> str:
    cur = ctx["current"]
    lines = [
        f"Formel „{ctx['key']}“ (Stufe {ctx['tier']}), aktuelle Ausdrücke:",
        *[f"- {e['name']} (Ebene {e['level']}): {e['expr']}" for e in cur["expressions"]],
        "Parameter: " + ", ".join(f"{k} = {v}" for k, v in cur["parameters"].items()),
        "Erlaubte Variablen (Ebene, Einheit): "
        + "; ".join(f"{k} ({v})" for k, v in ctx["variables"].items()),
        "Funktionen: " + ", ".join(ctx["functions"]),
        "Ausdrücke der Ebene plant gelten je Pflanze; auf Ebene stop nur über sum_plants(...), max_plants(...) "
        "usw. auf Pflanzenwerte zugreifen. Ein Ausdruck „duration“ (stop) ist Pflicht.",
    ]
    st = ctx["stats"]
    if st.get("n"):
        lines.append(
            f"Messungen: {st['n']} Stopps, mittlerer Fehler {st['mae']} min, {st['mape']} %, Verzerrung {st['bias']} min."
        )
        lines.append(
            "Verzerrung nach Gruppe: "
            + "; ".join(f"{g}: {v['bias']} min (n={v['n']})" for g, v in st["by_group"].items())
        )
    else:
        lines.append("Noch keine Messungen vorhanden: argumentiere mit Erfahrungswerten und Plausibilität.")
    if question:
        lines.append(f"Frage des Betriebs: {question}")
    if rounds:
        lines.append("\nBisherige Beiträge:")
        for x in rounds:
            lines.append(f"[{x['model']}]: {x['text']}")
            if x.get("formula"):
                lines.append(
                    "  Formelvorschlag: "
                    + " | ".join(f"{e['name']}: {e['expr']}" for e in x["formula"]["expressions"])
                )
    lines.append(
        {
            "open": "\nDu eröffnest: Bewerte die aktuelle Formel und schlage eine konkrete Verbesserung vor.",
            "reply": "\nAntworte auf den letzten Beitrag: Was stimmt, was nicht? Verbessere den Vorschlag.",
            "final": "\nLetzter Beitrag: Fasse die Diskussion zusammen und gib den gemeinsamen, endgültigen Vorschlag "
            "vollständig in formula an (oder die aktuelle Formel, wenn sie besser ist).",
        }[role]
    )
    return "\n".join(lines)


def _evaluate(
    db: Session, tenant_id: uuid.UUID | None, key: str, ctx: dict[str, Any], proposal: dict[str, Any]
) -> dict[str, Any]:
    if key != "time" or tenant_id is None:
        return {"n": 0}
    from app.learning.fit import error_metrics, fit_params
    from app.learning.samples import prepare_samples
    from app.learning.service import config_from
    from app.timemodel.estimate import Estimator

    current: CompiledFormula = ctx["_compiled"]
    tmp = FormulaVersion(
        formula_id=current.formula.id,
        version=0,
        expressions=proposal["expressions"],
        parameters=proposal["parameters"],
    )
    proposed = compile_version(current.formula, tmp)
    samples = prepare_samples(db, tenant_id, Estimator(db, tenant_id))
    used = [s for s in samples if s.used]
    if not used:
        return {"n": 0}
    meas = [s.measured for s in used]
    out: dict[str, Any] = {
        "n": len(used),
        "current": error_metrics([s.predict(current, current.params) for s in used], meas),
        "proposed_start": error_metrics([s.predict(proposed, proposed.params) for s in used], meas),
    }
    cfg = config_from(SettingsResolver(db, tenant_id))
    if len(used) >= 4:
        try:
            fitted = fit_params(samples, proposed, cfg, fit_staff=False)
            out["proposed_fitted"] = error_metrics([s.predict(proposed, fitted.params) for s in used], meas)
            out["fitted_params"] = {k: round(v, 4) for k, v in fitted.params.items()}
            fitted_now = fit_params(samples, current, cfg, fit_staff=False)
            out["current_fitted"] = error_metrics([s.predict(current, fitted_now.params) for s in used], meas)
        except (ValueError, ArithmeticError, AppError) as exc:  # a broken proposal must not stop the report
            out["fit_error"] = str(exc)[:200]
    return out


def run_debate(db: Session, debate: FormulaDebate, progress=None) -> FormulaDebate:
    progress = progress or (lambda f, m: None)
    tid = debate.tenant_id
    ctx = context_for(db, tid, debate.formula_key)
    current: CompiledFormula = ctx["_compiled"]
    models = {"a": db.get(AIModel, debate.model_a_id) if debate.model_a_id else None}
    models["b"] = db.get(AIModel, debate.model_b_id) if debate.model_b_id else models["a"]
    rounds: list[dict[str, Any]] = []
    turns = max(2, min(8, debate.n_rounds * 2))
    for i in range(turns):
        side = "a" if i % 2 == 0 else "b"
        role = "open" if i == 0 else "final" if i == turns - 1 else "reply"
        model = models[side]
        label = model.label if model else "Standardmodell"
        progress((i + 0.5) / turns, f"{label} ist am Zug …")
        text = _turn_text(ctx, debate.question, rounds, role)
        fake_ctx = {
            "turn": i,
            "turns": turns,
            "role": role,
            "label": label,
            "current": ctx["current"],
            "stats": ctx["stats"],
            "previous": rounds[-1]["formula"] if rounds and rounds[-1].get("formula") else None,
        }
        resp, used_model = ai.call(
            db, tid, "formula_debate", text, context=fake_ctx, model_id=model.id if model else None
        )
        data = resp.data or {}
        rounds.append(
            {
                "speaker": side,
                "model": used_model.label,
                "role": role,
                "text": str(data.get("text") or "").strip(),
                "formula": normalise(data.get("formula"), current.version),
                "agree": bool(data.get("agree")),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        debate.rounds = list(rounds)
        db.flush()
    final = next((x["formula"] for x in reversed(rounds) if x.get("formula")), None)
    if final is None:
        debate.proposal = {"valid": False, "problems": [{"detail": "kein Formelvorschlag"}]}
    else:
        problems = validate_expressions(debate.formula_key, final["expressions"], final["parameters"])
        debate.proposal = {**final, "valid": not problems, "problems": problems}
        if not problems:
            progress(0.95, "Vorschlag wird an den Messungen geprüft …")
            debate.evaluation = _evaluate(db, tid, debate.formula_key, ctx, final)
    debate.status = "done"
    return debate


def adopt(db: Session, actor, debate: FormulaDebate) -> FormulaVersion:
    """New version of the tenant's formula from the proposal (activated; revocable in the editor)."""
    from app.api.formulas import VersionIn, create_version

    if not (debate.proposal or {}).get("valid"):
        raise AppError(
            "errors.formula_invalid",
            detail="; ".join(p.get("detail", "") for p in debate.proposal.get("problems", [])),
        )
    ctx = context_for(db, actor.tenant_id, debate.formula_key)
    formula = ctx["_compiled"].formula
    params = dict(debate.proposal["parameters"])
    fitted = (debate.evaluation or {}).get("fitted_params") or {}
    for k, v in fitted.items():  # take the fitted values when the measurements gave them
        if k in params:
            params[k] = {**params[k], "value": v}
    v = create_version(
        db,
        actor,
        formula,
        VersionIn(
            expressions=debate.proposal["expressions"],
            parameters=params,
            note="Aus der KI-Diskussion",
            activate=True,
        ),
        source="debate",
    )
    debate.adopted_version_id = v.id
    return v


# ---------------------------------------------------------------------------- test model


def fake_turn(ctx: dict[str, Any]) -> dict[str, Any]:
    """Scripted discussion without AI: a fixed time per plant, then the stairs; the last turn agrees."""
    cur = ctx.get("current") or {"expressions": [], "parameters": {}}
    exprs = [dict(e) for e in cur["expressions"]]
    params = dict(cur["parameters"])
    st = ctx.get("stats") or {}
    err = f" Der mittlere Fehler liegt bei {st['mae']} Minuten ({st['mape']} %)." if st.get("n") else ""
    work = next((e for e in exprs if e["name"] == "work"), None)
    if ctx.get("role") == "open":
        if work and "h_fix" not in work["expr"]:
            work["expr"] = f"({work['expr']}) + h_fix"
            params["h_fix"] = 1.0
        return {
            "text": f"Testmodell ({ctx.get('label')}): Die Formel bildet Gewicht, Weg und Höhenmeter ab.{err} "
            "Es fehlt eine feste Zeit je Pflanze für Anheben, Sichern und Abstellen – ich schlage h_fix vor.",
            "formula": {"expressions": exprs, "parameters": params},
            "agree": False,
        }
    prev = ctx.get("previous") or {"expressions": exprs, "parameters": params}
    exprs = [dict(e) for e in prev["expressions"]]
    params = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in prev["parameters"].items()}
    work = next((e for e in exprs if e["name"] == "work"), None)
    if ctx.get("role") == "reply" and work and "k_steps" not in work["expr"]:
        work["expr"] = f"{work['expr']} + k_steps * steps"
        params["k_steps"] = 0.05
        return {
            "text": f"Testmodell ({ctx.get('label')}): Eine feste Zeit je Pflanze ist sinnvoll. Treppen kosten aber je "
            "Stufe Zeit, unabhängig von der Höhe – ich ergänze k_steps je Stufe.",
            "formula": {"expressions": exprs, "parameters": params},
            "agree": False,
        }
    return {
        "text": f"Testmodell ({ctx.get('label')}): Einverstanden. Gemeinsamer Vorschlag: feste Zeit je Pflanze und Zeit je "
        "Stufe; die Werte sollen an den Messungen angepasst werden.",
        "formula": {"expressions": exprs, "parameters": params},
        "agree": True,
    }

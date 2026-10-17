"""Loading, validating and evaluating formula versions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.formula.defaults import VARIABLES
from app.formula.parser import AGGREGATES, FUNCTIONS, FormulaError, evaluate, names, parse
from app.models.formulas import Formula, FormulaVersion

_TREE_CACHE: dict[str, tuple] = {}


def tree(src: str) -> tuple:
    t = _TREE_CACHE.get(src)
    if t is None:
        t = parse(src)
        if len(_TREE_CACHE) > 2000:
            _TREE_CACHE.clear()
        _TREE_CACHE[src] = t
    return t


@dataclass
class CompiledFormula:
    formula: Formula
    version: FormulaVersion
    plant_exprs: list[tuple[str, tuple]] = field(default_factory=list)
    stop_exprs: list[tuple[str, tuple]] = field(default_factory=list)
    params: dict[str, float] = field(default_factory=dict)

    def run(
        self, stop_vars: dict[str, Any], plants: list[dict[str, Any]], params: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """Evaluate plant-level expressions per plant, then stop-level ones. Returns stop results
        and fills each plant dict with its plant-level results."""
        prm = params if params is not None else self.params
        scope = {**prm, **stop_vars}
        for p in plants:
            local = {**scope, **p}
            for name, t in self.plant_exprs:
                local[name] = evaluate(t, local)
                p[name] = local[name]
        out: dict[str, Any] = {}
        for name, t in self.stop_exprs:
            out[name] = evaluate(t, {**scope, **out}, [{**prm, **p} for p in plants])
        return out


def validate_expressions(
    key: str, expressions: list[dict[str, Any]], parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Returns a list of problems (empty = ok): syntax errors with position, unknown names."""
    problems: list[dict[str, Any]] = []
    known = set(VARIABLES.get(key, {})) | set(parameters)
    plant_vars = {k for k, v in VARIABLES.get(key, {}).items() if v["level"] == "plant"}
    defined_plant: set[str] = set()
    defined_stop: set[str] = set()
    required = {"time": "duration", "price": "price"}.get(key)
    if required and not any(e.get("name") == required and e.get("level") == "stop" for e in expressions):
        problems.append(
            {
                "expression": required,
                "code": "missing",
                "detail": f"Ausdruck „{required}“ (Ebene Stopp) fehlt",
            }
        )
    for e in expressions:
        name, level, src = e.get("name", ""), e.get("level", "stop"), e.get("expr", "")
        if not name.isidentifier() or name in FUNCTIONS or name in AGGREGATES:
            problems.append({"expression": name, "code": "name", "detail": "ungültiger Name"})
            continue
        try:
            t = parse(src)
        except FormulaError as exc:
            problems.append({"expression": name, "code": exc.code, "detail": exc.detail, "pos": exc.pos})
            continue
        outer, inner = names(t)
        if level == "plant":
            allowed_outer = known | defined_plant | defined_stop
            unknown = sorted(n for n in outer | inner if n not in allowed_outer)
        else:
            unknown = sorted(n for n in outer if n not in known | defined_stop)
            unknown += sorted(n for n in inner if n not in known | defined_plant | defined_stop)
            bad_plant_outside = sorted(
                n for n in outer if n in (plant_vars | defined_plant) and n not in defined_stop
            )
            for n in bad_plant_outside:
                problems.append(
                    {
                        "expression": name,
                        "code": "plant_var_outside_aggregate",
                        "detail": f"„{n}“ gehört zu einer Pflanze und muss in sum_plants(…)/max_plants(…) stehen",
                    }
                )
        for n in unknown:
            problems.append({"expression": name, "code": "unknown_name", "detail": n})
        (defined_plant if level == "plant" else defined_stop).add(name)
    for pname, spec in parameters.items():
        if not pname.isidentifier():
            problems.append({"expression": pname, "code": "name", "detail": "ungültiger Parametername"})
        try:
            float(spec.get("value"))
        except (TypeError, ValueError):
            problems.append({"expression": pname, "code": "value", "detail": "Parameterwert fehlt"})
    return problems


def compile_version(formula: Formula, version: FormulaVersion) -> CompiledFormula:
    cf = CompiledFormula(formula=formula, version=version)
    for e in version.expressions:
        t = tree(e["expr"])
        (cf.plant_exprs if e.get("level") == "plant" else cf.stop_exprs).append((e["name"], t))
    cf.params = {k: float(v["value"]) for k, v in (version.parameters or {}).items()}
    return cf


def find_formula(db: Session, tenant_id: uuid.UUID | None, key: str, tier: int) -> Formula:
    if tenant_id is not None:
        own = db.scalar(
            select(Formula).where(Formula.tenant_id == tenant_id, Formula.key == key, Formula.tier == tier)
        )
        if own is not None and own.active_version_id:
            return own
    glob = db.scalar(
        select(Formula).where(Formula.tenant_id.is_(None), Formula.key == key, Formula.tier == tier)
    )
    if glob is None:
        glob = db.scalar(
            select(Formula).where(Formula.tenant_id.is_(None), Formula.key == key).order_by(Formula.tier)
        )
    if glob is None:
        # fresh database without seed (e.g. worker started before the API): create the defaults
        from app.core.db import system_session
        from app.formula.defaults import seed_formulas

        with system_session() as sdb:
            seed_formulas(sdb)
        glob = db.scalar(
            select(Formula).where(Formula.tenant_id.is_(None), Formula.key == key).order_by(Formula.tier)
        )
    if glob is None:
        raise NotFound("errors.not_found")
    return glob


def load_active(db: Session, tenant_id: uuid.UUID | None, key: str, tier: int = 1) -> CompiledFormula:
    formula = find_formula(db, tenant_id, key, tier)
    version = db.get(FormulaVersion, formula.active_version_id) if formula.active_version_id else None
    if version is None:
        raise AppError("errors.formula_eval", detail="keine aktive Version")
    try:
        return compile_version(formula, version)
    except FormulaError as exc:
        raise AppError("errors.formula_syntax", pos=exc.pos, detail=exc.detail) from exc

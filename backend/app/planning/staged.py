"""Staged tour optimisation (planning.strategy = staged).

Before the usual solver run (which keeps its full time budget planning.time_limit_s), about half
of that budget is spent on stages, so a staged plan takes about 1.5 times as long:

1. Fastest route: all stops with the default teams, only driving time counts. This is the
   reference (how short the tours could be) and shows which trips need how many people.
2. Team composition: several variants are solved briefly – the usual rule, teams sized after the
   trips of stage 1 ("route_based"), and uniform teams of 2 and 3 – and compared by the planning
   objective (costs, orders left out, later days). The team composition is the most variable lever:
   it is fixed before the solver runs and the solver cannot change it. Another variant than the rule
   is only taken if it is clearly better (VARIANT_MARGIN), because short runs scatter.
3. Search experiments: the chosen variant is solved again with other search methods (taken only if
   clearly better, SEARCH_MARGIN).
4. Final: the chosen variant gets the full time budget (with load planning). If a stage result is
   better than the final run, it is used. Measured on demo data, see DECISIONS D30.

With fixed teams (planning.form_teams = fixed) stage 2 has only one variant. Scenario plans keep a
single run so that variants stay comparable. Everything is written to plan.solver["stages"].
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any

from app.planning.inputs import PlanningInput
from app.planning.solver import SolveResult, solve

SEARCH_ALTERNATIVES = ("TABU_SEARCH", "SIMULATED_ANNEALING", "GUIDED_LOCAL_SEARCH")
VARIANT_MARGIN = 0.97  # another team composition must be at least 3 % better than the rule
SEARCH_MARGIN = 0.98  # another search method at least 2 % better


def score(inp: PlanningInput, res: SolveResult) -> dict[str, Any]:
    """The planning objective of a result (same weights as the solver) and its key figures."""
    st = inp.settings
    stops = {s.id: s for s in inp.stops}
    cost = 0.0
    drive = km = 0.0
    used: dict[str, Any] = {}
    for trip in res.trips:
        u = trip.unit
        minutes = trip.end - trip.start
        cost += minutes * (
            u.labour_cost_min * st.get("w_labour", 1.0) + u.vehicle_cost_min * st.get("w_vehicle", 1.0)
        )
        cost += trip.distance_km * u.cost_km * st.get("w_vehicle", 1.0)
        drive += trip.drive_min
        km += trip.distance_km
        used[u.key] = u
    fixed = sum(st.get("unit_fixed", 0) + u.day_index * st.get("day_preference", 0) for u in used.values())
    missing = [x for x in res.unassigned if x.get("order_id") in stops]
    penalty = sum(st.get("skip_penalty", 2000) * (1 + stops[x["order_id"]].priority) for x in missing)
    days = sorted({u.date for u in used.values()})
    return {
        "objective": round(cost + fixed + penalty, 2),
        "cost": round(cost, 2),
        "unassigned": len(missing),
        "units": len(used),
        "days": len(days),
        "last_day": days[-1].isoformat() if days else None,
        "drive_min": round(drive, 1),
        "distance_km": round(km, 1),
    }


def route_based_sizes(inp: PlanningInput, res: SolveResult, max_size: int) -> dict[str, list[int]]:
    """Per day: the team sizes the trips of the fastest-route stage need (biggest first)."""
    need: dict[str, dict[str, int]] = defaultdict(dict)
    for trip in res.trips:
        crew = max((max(s.stop.crew, s.stop.min_team) for s in trip.stops), default=1)
        day = trip.unit.date.isoformat()
        need[day][trip.unit.key] = max(need[day].get(trip.unit.key, 1), min(max_size, crew))
    return {d: sorted(v.values(), reverse=True) for d, v in need.items()}


def _with(inp: PlanningInput, **settings: Any) -> PlanningInput:
    return replace(inp, settings={**inp.settings, **settings})


def run_stages(
    db,
    base: PlanningInput,
    rebuild: Callable[[dict[str, Any]], PlanningInput],
    progress: Callable[[float, str], None],
    *,
    max_size: int,
    staff_count: int,
) -> tuple[PlanningInput, SolveResult | None, dict[str, Any]]:
    """Returns the input of the best variant (search method set), its best result so far and the
    report. rebuild(scenario_extra) forms the units again for a team variant (stops are reused)."""
    total = float(base.settings["time_limit_s"])
    large = len(base.stops) > int(base.settings.get("cluster_max", 180))
    report: dict[str, Any] = {"strategy": "staged", "time_limit_s": total}
    if not base.stops or not base.units:
        report["skipped"] = "no_stops" if not base.stops else "no_units"
        return base, None, report
    t_start = time.monotonic()

    # 1. fastest route with the usual teams: only driving time counts
    progress(0.08, "Schnellste Route wird gesucht …")
    t1 = max(0.5, total * 0.1)
    res_fast = solve(_with(base, objective_mode="fastest", time_limit_s=t1), db)
    fast = score(base, res_fast)
    report["fastest"] = {
        "stops": len(base.stops) - fast["unassigned"],
        "drive_min": fast["drive_min"],
        "distance_km": fast["distance_km"],
        "unassigned": fast["unassigned"],
        "units": fast["units"],
        "seconds": round(t1, 1),
    }

    # 2. team composition variants
    variants: list[tuple[str, dict[str, Any]]] = [("rule", {})]
    if base.team_mode != "fixed":
        sizes = route_based_sizes(base, res_fast, max_size)
        if sizes:
            variants.append(("route_based", {"day_team_sizes": sizes}))
        for n in (2, 3):
            if n <= max_size and n <= staff_count:
                variants.append((f"size_{n}", {"team_size": n, "strict_team_size": True}))
        if large:
            variants = variants[:2]  # big plans: only the rule and the route-based teams
    t2 = max(0.5, total * (0.3 if len(variants) > 1 else 0.1) / len(variants))
    rows = []
    best: tuple[float, str, PlanningInput, SolveResult] | None = None
    rule_obj: float | None = None
    for i, (key, extra) in enumerate(variants):
        progress(0.1 + 0.25 * i / len(variants), f"Teameinteilung „{key}“ wird geprüft …")
        inp = base if not extra else rebuild(extra)
        if not inp.units:
            rows.append({"key": key, "skipped": "no_units"})
            continue
        res = solve(_with(inp, time_limit_s=t2), db)
        sc = score(inp, res)
        rows.append({"key": key, **sc, "team_sizes": _sizes(inp)})
        if key == "rule":
            rule_obj = sc["objective"]
        clearly_better = rule_obj is None or sc["objective"] <= rule_obj * VARIANT_MARGIN
        if best is None or (sc["objective"] < best[0] and clearly_better):
            best = (sc["objective"], key, inp, res)
    report["variants"] = rows
    if best is None:
        return base, None, report
    best_obj, best_key, best_inp, best_res = best
    report["chosen"] = best_key

    # 3. search experiments on the chosen variant
    search_rows = []
    current = str(best_inp.settings.get("metaheuristic", "GUIDED_LOCAL_SEARCH"))
    chosen_search = current
    if not large:
        alternatives = [m for m in SEARCH_ALTERNATIVES if m != current][:2]
        t3 = max(0.5, total * 0.1 / max(1, len(alternatives)))
        for mh in alternatives:
            progress(0.38, f"Suchverfahren {mh} wird probiert …")
            res = solve(_with(best_inp, metaheuristic=mh, time_limit_s=t3), db)
            sc = score(best_inp, res)
            search_rows.append({"metaheuristic": mh, **sc})
            if sc["objective"] <= best_obj * SEARCH_MARGIN:
                best_obj, best_res, chosen_search = sc["objective"], res, mh
    report["search"] = search_rows
    report["chosen_search"] = chosen_search
    report["best_objective"] = best_obj

    # 4. the final run gets the full budget (never less search than a single run)
    used = time.monotonic() - t_start
    final = total
    report["final_time_limit_s"] = round(final, 1)
    report["stage_seconds"] = round(used, 1)
    return _with(best_inp, metaheuristic=chosen_search, time_limit_s=final), best_res, report


def _sizes(inp: PlanningInput) -> dict[str, list[int]]:
    out: dict[date, list[int]] = defaultdict(list)
    for u in inp.units:
        out[u.date].append(u.team_size)
    return {d.isoformat(): sorted(v, reverse=True) for d, v in sorted(out.items())}

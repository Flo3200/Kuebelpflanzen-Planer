"""Explanations for stops that could not be planned (package D).

With fixed teams (planning.form_teams = fixed) a plan is always created; stops without a fitting
team appear as unassigned with their reason and a hint which team or person would solve it. Hints
are structured ({code, params}) and translated in the UI (planning.hints.<code>).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from types import SimpleNamespace
from typing import Any

from app.planning.inputs import PlanningInput, StopIn, fits_geometry
from app.planning.solver import ServiceCache

INFO_ONLY = {"vehicle_replaced"}  # team issues that do not stop the team from working
TEAM_REASONS = {"team_too_small", "team_limit", "no_units", "no_day", "no_capacity"}
VEHICLE_REASONS = {"vehicle_too_small", "too_heavy_for_vehicle", "load_plan"}


def _issue_summary(issues: list[dict[str, Any]], days: set[str] | None) -> list[dict[str, Any]]:
    """Distinct team problems on the given days (one line per team and reason)."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for i in issues:
        if days is not None and (i["date"] not in days or i["reason"] in INFO_ONLY):
            continue
        k = (i["team_id"], i["reason"])
        if k not in seen:
            seen[k] = {**i, "dates": [i["date"]]}
        else:
            seen[k]["dates"].append(i["date"])
    return list(seen.values())


def explain(inp: PlanningInput, unassigned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds `need` (persons) and `hints` to unassigned stops; only for fixed teams."""
    if inp.team_mode != "fixed":
        return unassigned
    stops: dict[str, StopIn] = {s.id: s for s in inp.stops}
    names = inp.names
    in_teams = {m for t in inp.fixed_teams for m in t["member_ids"]}
    free_staff = sorted(names.get(i, "?") for i in inp.staff_ids if i not in in_teams)
    cache = ServiceCache(inp)
    out = []
    for u in unassigned:
        s = stops.get(u.get("order_id", ""))
        reason = u.get("reason")
        if s is None or reason not in TEAM_REASONS | VEHICLE_REASONS:
            out.append(u)
            continue
        need = max(s.crew, s.min_team)
        days = {d.isoformat() for d in s.dates} if s.dates is not None else None
        hints: list[dict[str, Any]] = []
        if not inp.fixed_teams:
            hints.append({"code": "no_teams", "params": {}})
        elif reason in VEHICLE_REASONS:
            fitting = [
                v
                for v in inp.vehicles
                if fits_geometry(s, SimpleNamespace(vehicle=v, trailer=None)) and s.weight <= v.payload
            ]
            if fitting:
                team_of = {t["vehicle_id"]: t["name"] for t in inp.fixed_teams if t["vehicle_id"]}
                hints.append(
                    {
                        "code": "use_vehicle",
                        "params": {
                            "vehicles": ", ".join(
                                v.name + (f" ({team_of[v.id]})" if v.id in team_of else "") for v in fitting
                            )
                        },
                    }
                )
            else:
                hints.append({"code": "bigger_vehicle", "params": {"weight": round(s.weight)}})
        else:
            # persons needed with the teams that exist (weaker members mean more carriers)
            options = [
                (cache.get(s, un).crew - un.team_size, cache.get(s, un).crew, un)
                for un in inp.units
                if un.fixed_team_id and not un.fixed_team_id.startswith("forced:")
            ]
            if options:
                deficit, need, best = min(options, key=lambda o: (o[0], o[1]))
                team_name = names.get(best.fixed_team_id or "", "")
            else:
                largest = max(inp.fixed_teams, key=lambda t: len(t["member_ids"]))
                deficit, team_name = need - len(largest["member_ids"]), largest["name"]
            big_enough = [t for t in inp.fixed_teams if len(t["member_ids"]) >= need]
            formed = {un.fixed_team_id for un in inp.units}
            idle_big = [t for t in big_enough if t["id"] not in formed or not options]
            if deficit > 0 and idle_big:
                # a team of the right size exists but could not work on the possible days
                problems = _issue_summary(
                    [i for i in inp.team_issues if i["team_id"] in {t["id"] for t in idle_big}], days
                )
                hints.append(
                    {
                        "code": "big_team_unavailable",
                        "params": {"teams": ", ".join(t["name"] for t in idle_big), "need": need},
                    }
                )
                hints += [_issue_hint(p) for p in problems[:3]]
            elif deficit > 0:
                hints.append(
                    {
                        "code": "add_person",
                        "params": {
                            "team": team_name,
                            "n": deficit,
                            "need": need,
                            "persons": ", ".join(free_staff[:3]),
                        },
                    }
                )
            problems = _issue_summary(inp.team_issues, days)
            if reason in ("no_units", "no_day") and problems:
                hints += [_issue_hint(p) for p in problems[:3]]
            elif not hints:
                hints.append({"code": "more_days", "params": {}})
        unique = list({json.dumps(h, sort_keys=True): h for h in hints}.values())
        out.append({**u, "need": need, "hints": unique})
    return out


def _issue_hint(p: dict[str, Any]) -> dict[str, Any]:
    dates = sorted(p.get("dates") or [p["date"]])
    return {
        "code": f"team_{p['reason']}",
        "params": {
            "team": p.get("team") or "",
            "names": ", ".join(p.get("names") or []),
            "other": p.get("other_team") or "",
            "days": ", ".join(date.fromisoformat(d).strftime("%d.%m.") for d in dates[:4])
            + (" …" if len(dates) > 4 else ""),
        },
    }


def team_issue_overview(inp: PlanningInput) -> list[dict[str, Any]]:
    """Per team and reason: on how many days (for the plan page)."""
    counts = Counter((i["team_id"], i["reason"]) for i in inp.team_issues)
    out = []
    for p in _issue_summary(inp.team_issues, None):
        out.append(
            {**_issue_hint(p), "team_id": p["team_id"], "days_count": counts[(p["team_id"], p["reason"])]}
        )
    return out

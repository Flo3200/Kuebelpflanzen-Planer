"""Vehicle routing with OR-Tools.

Every unit (day × vehicle × team) is one vehicle of the solver. Dimensions: time (service time
depends on the unit's team), weight, floor area and volume. Several trips per day are modelled
with optional reload nodes at the depot (capacity resets via slack, as in the OR-Tools
"cvrp_reload" example). Stops can be dropped with a penalty, so a solution always exists.
Matrices are registered with RegisterTransitMatrix so evaluation stays in C++.
"""

from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.planning.inputs import PlanningInput, StopIn, Unit, ceil_min, fits_geometry
from app.routing.provider import cached_matrix

DAY = 24 * 60


@dataclass
class ServiceInfo:
    feasible: bool
    service_min: float  # planning duration incl. buffer and parking
    predicted_min: float  # expected duration on site
    crew: int
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass
class SolvedStop:
    stop: StopIn
    position: int
    arrival: int
    start: int
    end: int
    service_min: float
    predicted_min: float
    drive_from_prev_min: float
    distance_from_prev_km: float
    warnings: tuple[str, ...] = ()


@dataclass
class SolvedTrip:
    unit: Unit
    trip_no: int
    stops: list[SolvedStop]
    start: int
    end: int
    distance_km: float
    drive_min: float
    unload_min: float
    breaks: list[dict[str, int]] = field(default_factory=list)


@dataclass
class SolveResult:
    trips: list[SolvedTrip] = field(default_factory=list)
    unassigned: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class ServiceCache:
    """Feasibility and service time of a stop for a unit's team profile."""

    def __init__(self, inp: PlanningInput) -> None:
        self.inp = inp
        self.cache: dict[tuple, ServiceInfo] = {}

    def get(self, stop: StopIn, unit: Unit) -> ServiceInfo:
        key = (unit.profile_key(self.inp.shared_equipment), stop.id)
        info = self.cache.get(key)
        if info is None:
            info = self._compute(stop, unit)
            self.cache[key] = info
        return info

    def _compute(self, stop: StopIn, unit: Unit) -> ServiceInfo:
        est = self.inp.estimator
        paths = stop.paths or est.paths_for(stop.order)
        calcs = [
            est.plant_calc(
                p,
                paths.get(p.access_path_id) or paths[None],
                equipment=unit.equipment + self.inp.shared_equipment,
                solo_limits=[m.solo_kg for m in unit.members],
                carry_factor=unit.members[0].carry_factor,
            )
            for p in stop.plants
        ]
        crew = max(max((c.crew.crew for c in calcs), default=1), stop.min_team)
        warnings: tuple[str, ...] = ()
        if any(c.crew.exceeds_max for c in calcs):
            if not self.inp.settings.get("allow_over_limit", True):
                return ServiceInfo(False, 0, 0, crew, "team_limit")
            warnings = ("exceeds_team_limit",)
        if unit.team_size < crew:
            return ServiceInfo(False, 0, 0, crew, "team_too_small")
        duration = est.stop_duration(calcs, unit.team_size, unit.carry_speed)
        service = duration * self.inp.settings["quantile_factor"] + self.inp.settings["parking_min"]
        return ServiceInfo(True, service, duration, crew, None, warnings)


def _enum(enum_type, name: str, fallback: str) -> int:
    value = getattr(enum_type, name, None)
    return value if isinstance(value, int) else getattr(enum_type, fallback)


def angle_groups(inp: PlanningInput, stops: list[StopIn], n_groups: int) -> list[list[StopIn]]:
    lat0, lon0 = inp.depot
    keyed = sorted(
        stops, key=lambda s: math.atan2(s.lat - lat0, (s.lon - lon0) * math.cos(math.radians(lat0)))
    )
    size = math.ceil(len(keyed) / n_groups)
    return [keyed[i : i + size] for i in range(0, len(keyed), size)]


def allocate_units(groups: list[list[StopIn]], units: list[Unit]) -> list[list[Unit]]:
    """Distribute units over region groups proportionally to workload, day by day."""
    demand = [max(1.0, sum(len(s.plants) + 2 for s in g)) for g in groups]
    share = [d / sum(demand) for d in demand]
    alloc: list[list[Unit]] = [[] for _ in groups]
    got = [0.0] * len(groups)
    for u in sorted(units, key=lambda u: (u.date, -u.team_size, -u.cap_weight)):
        total = sum(got) + 1
        g = max(range(len(groups)), key=lambda k: share[k] - got[k] / total)
        alloc[g].append(u)
        got[g] += 1
    return alloc


def solve(
    inp: PlanningInput,
    db=None,
    cap_scale: dict[str, float] | None = None,
    forbidden_pairs: set[tuple[str, str]] | None = None,
) -> SolveResult:
    started = _time.monotonic()
    cache = ServiceCache(inp)
    result = SolveResult()
    result.unassigned += [dict(u) for u in inp.unplannable]
    feasible_stops: list[StopIn] = []
    allowed: dict[str, list[int]] = {}
    for s in inp.stops:
        options = []
        reasons = defaultdict(int)
        for k, u in enumerate(inp.units):
            if s.dates is not None and u.date not in s.dates:
                reasons["no_day"] += 1
                continue
            if s.pinned_unit and u.key != s.pinned_unit:
                continue
            info = cache.get(s, u)
            if not info.feasible:
                reasons[info.reason or "team_too_small"] += 1
                continue
            if not fits_geometry(s, u):
                reasons["vehicle_too_small"] += 1
                continue
            if s.weight > u.cap_weight:
                reasons["too_heavy_for_vehicle"] += 1
                continue
            options.append(k)
        if s.experiment and options:
            bigger = [k for k in options if inp.units[k].team_size > cache.get(s, inp.units[k]).crew]
            if bigger:
                options = bigger
            else:
                s.experiment = False
        if not options:
            reason = max(reasons, key=reasons.get) if reasons else ("no_units" if not inp.units else "no_day")
            if s.pinned_unit:
                reason = "pinned_unit_unavailable"
            result.unassigned.append({"order_id": s.id, "number": s.number, "reason": reason})
            continue
        allowed[s.id] = options
        feasible_stops.append(s)

    if not feasible_stops or not inp.units:
        result.stats = {"seconds": round(_time.monotonic() - started, 2), "groups": 0}
        return result

    n_groups = max(1, math.ceil(len(feasible_stops) / inp.settings["cluster_max"]))
    if n_groups > 1:
        groups = angle_groups(inp, feasible_stops, n_groups)
        unit_alloc = allocate_units(groups, inp.units)
    else:
        groups, unit_alloc = [feasible_stops], [list(inp.units)]
    limit_total = inp.settings["time_limit_s"]
    group_stats = []
    for g, (stops, units) in enumerate(zip(groups, unit_alloc, strict=True)):
        local_units = list(units)
        local_allowed = {
            s.id: [local_units.index(inp.units[k]) for k in allowed[s.id] if inp.units[k] in local_units]
            for s in stops
        }
        movable = [s for s in stops if local_allowed[s.id]]
        for s in stops:
            if not local_allowed[s.id]:
                result.unassigned.append({"order_id": s.id, "number": s.number, "reason": "no_capacity"})
        share = len(movable) / max(1, len(feasible_stops))
        limit = max(1.0, limit_total * share) if n_groups > 1 else limit_total
        trips, dropped, stats = _solve_group(
            inp,
            db,
            cache,
            movable,
            local_units,
            local_allowed,
            limit,
            cap_scale or {},
            forbidden_pairs or set(),
        )
        result.trips += trips
        for s in dropped:
            result.unassigned.append({"order_id": s.id, "number": s.number, "reason": "no_capacity"})
        group_stats.append({"group": g, "stops": len(movable), "units": len(local_units), **stats})
    result.stats = {
        "seconds": round(_time.monotonic() - started, 2),
        "groups": len(groups),
        "group_stats": group_stats,
    }
    return result


def _solve_group(
    inp: PlanningInput,
    db,
    cache: ServiceCache,
    stops: list[StopIn],
    units: list[Unit],
    allowed: dict[str, list[int]],
    time_limit: float,
    cap_scale: dict[str, float],
    forbidden_pairs: set[tuple[str, str]],
) -> tuple[list[SolvedTrip], list[StopIn], dict[str, Any]]:
    st = inp.settings
    S = len(stops)
    reload_owner: list[int] = []
    for k, u in enumerate(units):
        reload_owner += [k] * max(0, u.max_trips - 1)
    R = len(reload_owner)
    N = 1 + S + R
    loc = [0] + list(range(1, S + 1)) + [0] * R
    points = [inp.depot] + [(s.lat, s.lon) for s in stops]
    matrix = cached_matrix(db, inp.estimator.routing, points)
    travel = [[matrix.duration_min[loc[i]][loc[j]] for j in range(N)] for i in range(N)]
    dist = [[matrix.distance_km[loc[i]][loc[j]] for j in range(N)] for i in range(N)]

    manager = pywrapcp.RoutingIndexManager(N, len(units), 0)
    routing = pywrapcp.RoutingModel(manager)
    solver = routing.solver()

    # ---- time per unit profile
    time_cb: dict[tuple, int] = {}
    service_of: list[list[float]] = []
    vehicle_time_cb: list[int] = []
    for k, u in enumerate(units):
        # service depends only on the team profile, so units with equal teams share one matrix;
        # reload nodes of other units are never visited by this unit (allowed vehicles)
        svc = [0.0] * N
        for i, s in enumerate(stops, start=1):
            info = cache.get(s, u)
            svc[i] = info.service_min if info.feasible else 0.0
        for r_i in range(R):
            svc[1 + S + r_i] = u.unload_min
        service_of.append(svc)
        key = (u.profile_key(inp.shared_equipment), round(u.drive_factor, 3), u.unload_min)
        if key not in time_cb:
            df = u.drive_factor
            m = [
                [0 if i == j else ceil_min(svc[i]) + ceil_min(travel[i][j] / df) for j in range(N)]
                for i in range(N)
            ]
            time_cb[key] = routing.RegisterTransitMatrix(m)
        vehicle_time_cb.append(time_cb[key])
    routing.AddDimensionWithVehicleTransits(vehicle_time_cb, DAY, DAY, False, "Time")
    tdim = routing.GetDimensionOrDie("Time")

    # ---- cost: distance per unit (cents); time costs via span cost
    cost_cb: dict[float, int] = {}
    for k, u in enumerate(units):
        rate = round(u.cost_km * st["w_vehicle"] * 100, 4)
        if rate not in cost_cb:
            m = [[int(round(dist[i][j] * rate)) for j in range(N)] for i in range(N)]
            cost_cb[rate] = routing.RegisterTransitMatrix(m)
        routing.SetArcCostEvaluatorOfVehicle(cost_cb[rate], k)
        span = (u.labour_cost_min * st["w_labour"] + u.vehicle_cost_min * st["w_vehicle"]) * 100
        tdim.SetSpanCostCoefficientForVehicle(max(1, int(round(span))), k)
        routing.SetFixedCostOfVehicle(
            int(round((st["unit_fixed"] + u.day_index * st["day_preference"]) * 100)), k
        )
        start, end = routing.Start(k), routing.End(k)
        tdim.CumulVar(start).SetRange(u.start, u.end)
        tdim.CumulVar(end).SetMax(u.hard_end)
        overtime = (u.labour_cost_min * st["overtime_surcharge"] + st["overtime_penalty"]) * 100
        tdim.SetCumulVarSoftUpperBound(end, u.end, max(1, int(round(overtime))))
        routing.AddVariableMinimizedByFinalizer(tdim.CumulVar(start))
        routing.AddVariableMinimizedByFinalizer(tdim.CumulVar(end))

    # ---- breaks (Working Time Act): one break between 3 h and 6 h after the start of work;
    # the solver places it between visits (or after the end of a short day)
    for k, u in enumerate(units):
        if u.break_min > 0:
            interval = solver.FixedDurationIntervalVar(
                u.start + 180, u.start + 360, int(u.break_min), False, f"break-{k}"
            )
            tdim.SetBreakIntervalsOfVehicle([interval], k, [ceil_min(x) for x in service_of[k]])

    # ---- customer time windows
    for i, s in enumerate(stops, start=1):
        if not s.windows or st["time_windows"] == "off":
            continue
        idx = manager.NodeToIndex(i)
        lo = min(w[0] for w in s.windows)
        hi = max(w[1] for w in s.windows)
        if st["time_windows"] == "hard":
            tdim.CumulVar(idx).SetRange(lo, hi)
            spans = sorted((w[0], w[1]) for w in s.windows)
            for (_a0, a1), (b0, _b1) in zip(spans, spans[1:], strict=False):
                if b0 > a1 + 1:
                    tdim.CumulVar(idx).RemoveInterval(a1 + 1, b0 - 1)
        else:
            pen = max(1, int(round(st["tw_penalty"] * 100)))
            tdim.SetCumulVarSoftLowerBound(idx, lo, pen)
            tdim.SetCumulVarSoftUpperBound(idx, hi, pen)

    # ---- capacities with reload nodes
    def add_capacity(name: str, per_stop: list[int], caps: list[int]) -> None:
        demand = [0] * N
        for i in range(S):
            demand[1 + i] = per_stop[i]
        for r_i, owner in enumerate(reload_owner):
            demand[1 + S + r_i] = -caps[owner]
        cb = routing.RegisterUnaryTransitVector(demand)
        routing.AddDimensionWithVehicleCapacity(cb, max(caps) if caps else 0, caps, True, name)
        dim = routing.GetDimensionOrDie(name)
        for i in range(1, 1 + S):
            dim.SlackVar(manager.NodeToIndex(i)).SetValue(0)
        for k in range(len(units)):
            dim.SlackVar(routing.Start(k)).SetValue(0)

    def scale(u: Unit, kind: str) -> float:
        return cap_scale.get(f"{u.key}|{kind}", cap_scale.get(u.key, 1.0))

    add_capacity("Weight", [int(math.ceil(s.weight)) for s in stops], [int(u.cap_weight) for u in units])
    add_capacity(
        "Area",
        [int(math.ceil(s.area * 100)) for s in stops],
        [int(u.cap_area * 100 * scale(u, "area")) for u in units],
    )
    add_capacity(
        "Volume",
        [int(math.ceil(s.volume * 1000)) for s in stops],
        [int(u.cap_volume * 1000 * scale(u, "volume")) for u in units],
    )

    # ---- allowed units, dropping penalties, reloads
    for i, s in enumerate(stops, start=1):
        idx = manager.NodeToIndex(i)
        # -1 = not performed (dropped); SetAllowedVehiclesForIndex is not usable from Python here
        routing.VehicleVar(idx).SetValues([-1] + sorted(allowed[s.id]))
        if st["objective"] == "profit":
            penalty = max(1.0, s.price_net) * 100
        else:
            penalty = st["skip_penalty"] * 100 * (1 + s.priority)
        if s.pinned_unit:
            penalty *= 50
        routing.AddDisjunction([idx], int(penalty))
    for r_i, owner in enumerate(reload_owner):
        idx = manager.NodeToIndex(1 + S + r_i)
        routing.VehicleVar(idx).SetValues([-1, owner])
        routing.AddDisjunction([idx], 0)

    # ---- incompatible stops: never on the same unit
    node_of = {s.id: i for i, s in enumerate(stops, start=1)}
    for a, b in forbidden_pairs:
        if a in node_of and b in node_of:
            ia, ib = manager.NodeToIndex(node_of[a]), manager.NodeToIndex(node_of[b])
            diff = solver.IsDifferentVar(routing.VehicleVar(ia), routing.VehicleVar(ib))
            solver.Add(diff + (1 - routing.ActiveVar(ia)) + (1 - routing.ActiveVar(ib)) >= 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = _enum(
        routing_enums_pb2.FirstSolutionStrategy, st["first_solution"], "PARALLEL_CHEAPEST_INSERTION"
    )
    params.local_search_metaheuristic = _enum(
        routing_enums_pb2.LocalSearchMetaheuristic, st["metaheuristic"], "GUIDED_LOCAL_SEARCH"
    )
    params.time_limit.FromMilliseconds(int(time_limit * 1000))
    t0 = _time.monotonic()
    solution = routing.SolveWithParameters(params)
    seconds = round(_time.monotonic() - t0, 2)
    if solution is None:
        return [], list(stops), {"status": "no_solution", "seconds": seconds}

    trips: list[SolvedTrip] = []
    served: set[int] = set()
    break_at: dict[int, int] = {}
    intervals = solution.IntervalVarContainer()
    for i in range(intervals.Size()):
        el = intervals.Element(i)
        name = el.Var().Name()
        if name.startswith("break-") and el.PerformedValue():
            break_at[int(name.split("-")[1])] = el.StartValue()
    for k, u in enumerate(units):
        index = routing.Start(k)
        seq: list[tuple[int, int]] = []
        while True:
            node = manager.IndexToNode(index)
            seq.append((node, solution.Value(tdim.CumulVar(index))))
            if routing.IsEnd(index):
                break
            index = solution.Value(routing.NextVar(index))
        if len(seq) <= 2:
            continue
        first_trip_index = len(trips)
        svc = service_of[k]
        trip_no = 1
        cur: list[SolvedStop] = []
        trip_start = seq[0][1]
        dist_sum = drive_sum = 0.0
        prev_node, prev_dep = seq[0][0], seq[0][1]
        for node, cum in seq[1:]:
            tr = travel[prev_node][node] / u.drive_factor
            dk = dist[prev_node][node]
            dist_sum += dk
            drive_sum += tr
            if 1 <= node <= S:
                s = stops[node - 1]
                served.add(node)
                info = cache.get(s, u)
                cur.append(
                    SolvedStop(
                        s,
                        len(cur) + 1,
                        int(round(prev_dep + tr)),
                        cum,
                        int(round(cum + svc[node])),
                        round(svc[node], 1),
                        round(info.predicted_min, 1),
                        round(tr, 1),
                        round(dk, 2),
                        info.warnings,
                    )
                )
                prev_dep = cum + svc[node]
            else:  # depot end or reload
                arrival = int(round(prev_dep + tr))
                if cur:
                    trips.append(
                        SolvedTrip(
                            u,
                            trip_no,
                            cur,
                            trip_start,
                            arrival,
                            round(dist_sum, 2),
                            round(drive_sum, 1),
                            svc[node] if node > S else 0.0,
                        )
                    )
                    trip_no += 1
                cur = []
                dist_sum = drive_sum = 0.0
                trip_start = cum + (svc[node] if node > S else 0)
                prev_dep = trip_start
            prev_node = node
        if k in break_at:
            b = break_at[k]
            day = trips[first_trip_index:]
            if day and b < day[-1].end:
                # during a trip or between two trips (at the depot): attach to the trip before it
                owner = [t for t in day if t.start <= b] or day[:1]
                owner[-1].breaks.append(
                    {"trip_no": owner[-1].trip_no, "start": b, "end": b + int(u.break_min)}
                )
    dropped = [s for i, s in enumerate(stops, start=1) if i not in served]
    stats = {
        "status": "ok",
        "seconds": seconds,
        "objective": solution.ObjectiveValue(),
        "dropped": len(dropped),
    }
    return trips, dropped, stats

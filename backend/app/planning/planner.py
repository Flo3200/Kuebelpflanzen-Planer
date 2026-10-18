"""Planning run: build input, solve (with re-solves for incompatible plants and load-plan
failures), write tours, compute costs and KPIs; manual moves and replanning."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orders import PickupOrder, Plant
from app.models.planning import Plan, Tour, TourStop
from app.planning.hints import explain, team_issue_overview
from app.planning.inputs import PlanningInput, build_input
from app.planning.solver import SolvedTrip, SolveResult, solve
from app.routing.provider import cached_matrix
from app.settings.service import SettingsResolver
from app.timemodel.costitems import allocate_to_stops
from app.timemodel.costitems import load_items as load_cost_items
from app.timemodel.costitems import trip_costs as trip_cost_items

PALETTE = [
    "#2b5139",
    "#c2693e",
    "#2f5f8a",
    "#8a6d1d",
    "#7b4b8a",
    "#3d8a85",
    "#a33b4f",
    "#5c7a2e",
    "#4a5a9a",
    "#b0782a",
]

# Phase 5 plugs a load planner in here: fn(db, plan_input, trip) -> (ok, message, payload)
PackCheck = Callable[[Session, PlanningInput, SolvedTrip], tuple[bool, str, dict[str, Any]]]


def pack_check_default() -> PackCheck | None:
    try:
        from app.packing.service import pack_trip_check
    except ModuleNotFoundError:
        return None
    return pack_trip_check


def _kept_tours(db: Session, plan: Plan, from_date: date | None) -> list[Tour]:
    """Tours that stay untouched: before the replanning date, already started/done, or fixed."""
    keep = []
    for t in db.scalars(select(Tour).where(Tour.plan_id == plan.id)):
        if (from_date and t.date < from_date) or t.status in ("in_progress", "done") or t.fixed:
            keep.append(t)
    return keep


def run_plan(
    db: Session,
    plan: Plan,
    progress: Callable[[float, str], None] | None = None,
    pack_check: PackCheck | None = None,
) -> Plan:
    progress = progress or (lambda f, m: None)
    from_date = date.fromisoformat(plan.options["from_date"]) if plan.options.get("from_date") else None
    kept = _kept_tours(db, plan, from_date)
    kept_ids = {t.id for t in kept}
    kept_orders: set[str] = set()
    forced_units: list[dict[str, Any]] = []
    pins: dict[str, str] = {}
    for t in kept:
        stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == t.id)))
        if t.fixed and t.status == "planned" and not (from_date and t.date < from_date):
            # fixed tours are re-solved inside their unit (sequence may be improved)
            forced_units.append({**t.unit, "date": t.date.isoformat()})
            for s in stops:
                pins[str(s.order_id)] = t.unit_key
        else:
            kept_orders |= {str(s.order_id) for s in stops}
    # fixed single stops in non-kept tours
    for t in db.scalars(select(Tour).where(Tour.plan_id == plan.id)):
        if t.id in kept_ids:
            continue
        for s in db.scalars(select(TourStop).where(TourStop.tour_id == t.id, TourStop.fixed.is_(True))):
            pins[str(s.order_id)] = t.unit_key
            forced_units.append({**t.unit, "date": t.date.isoformat()})
    start = max(plan.start_date, from_date) if from_date else plan.start_date
    days = plan.days - (start - plan.start_date).days
    progress(0.05, "Eingaben werden vorbereitet …")
    order_ids = None
    if plan.options.get("order_ids"):
        order_ids = [uuid.UUID(x) for x in plan.options["order_ids"]]
    inp = build_input(
        db,
        plan.tenant_id,
        start,
        max(1, days),
        plan.direction,
        order_ids=order_ids,
        scenario=plan.scenario,
        pins=pins,
        forced_units=forced_units,
    )
    inp.stops = [s for s in inp.stops if s.id not in kept_orders]
    if plan.options.get("time_limit_s"):
        inp.settings["time_limit_s"] = float(plan.options["time_limit_s"])
    pack_check = (
        pack_check
        if pack_check is not None
        else (pack_check_default() if plan.options.get("pack", True) else None)
    )
    cap_scale: dict[str, float] = {}
    forbidden: set[tuple[str, str]] = set()
    forbidden_assign: set[tuple[str, str]] = set()
    pack_strikes: dict[tuple[str, str], int] = {}
    pack_cache: dict[tuple[Any, ...], tuple[bool, str, dict[str, Any]]] = {}
    final_done = False
    plant_to_order = {str(p.id): s.id for s in inp.stops for p in s.plants}
    attempts = 0
    pack_failures: dict[str, str] = {}
    pack_results: dict[tuple[str, int], dict[str, Any]] = {}
    while True:
        progress(0.15 + 0.6 * min(attempts, 4) / 5, "Touren werden optimiert …")
        last_round = attempts >= inp.settings["pack_retry_limit"]
        res = solve(inp, db, cap_scale, forbidden, forbidden_assign)
        # incompatible plants on the same unit -> forbid the pair and solve again
        violations = set()
        by_unit: dict[str, set[str]] = defaultdict(set)
        for trip in res.trips:
            by_unit[trip.unit.key] |= {s.stop.id for s in trip.stops}
        for s in inp.stops:
            for other_plant in s.incompatible:
                o = plant_to_order.get(other_plant)
                if o and any(s.id in ids and o in ids for ids in by_unit.values()):
                    violations.add(tuple(sorted((s.id, o))))
        new_pairs = violations - forbidden
        failed_units: set[str] = set()
        if pack_check is not None and not new_pairs:
            progress(0.8, "Ladepläne werden geprüft …")
            pack_failures.clear()
            for trip in res.trips:
                # identical trips (same vehicles, same stops in the same order) are not packed twice
                ck = (
                    trip.unit.vehicle.id,
                    trip.unit.trailer.id if trip.unit.trailer else None,
                    tuple(st.stop.id for st in trip.stops),
                )
                if ck not in pack_cache:
                    pack_cache[ck] = pack_check(db, inp, trip)
                ok, message, payload = pack_cache[ck]
                pack_results[(trip.unit.key, trip.trip_no)] = {"ok": ok, "message": message, **payload}
                if not ok:
                    failed_units.add(trip.unit.key)
                    pack_failures[trip.unit.key] = message
                    # Stops whose plants could not be placed: never again on this unit if the vehicle
                    # cannot take them at all (door, height); after a second crowding failure as well.
                    bad = {u["plant_id"]: u["reason"] for u in payload.get("unplaced", [])}
                    for st in trip.stops:
                        reasons = [bad[str(p.id)] for p in st.stop.plants if str(p.id) in bad]
                        if not reasons:
                            continue
                        combo = (st.stop.id, trip.unit.key)
                        pack_strikes[combo] = pack_strikes.get(combo, 0) + 1
                        if (
                            any(r not in ("space", "payload") for r in reasons)
                            or pack_strikes[combo] >= 2
                            or last_round
                        ):
                            forbidden_assign.add(combo)
        attempts += 1
        if new_pairs and attempts <= 3:
            forbidden |= new_pairs
            continue
        if failed_units and not final_done and attempts <= inp.settings["pack_retry_limit"] + 1:
            # in the last round every stop that did not fit is kept off that unit for good
            final_done = last_round
            for key in failed_units:
                cap_scale[key] = cap_scale.get(key, 1.0) * inp.settings["capacity_shrink"]
            pack_results.clear()
            continue
        break
    progress(0.9, "Ergebnis wird gespeichert …")
    write_results(db, plan, inp, res, kept, pack_results)
    plan.solver = {
        **res.stats,
        "attempts": attempts,
        "capacity_scale": cap_scale,
        "pack_failures": pack_failures,
        "forbidden_pairs": len(forbidden),
        "forbidden_assignments": len(forbidden_assign),
        "team_mode": inp.team_mode,
        # fixed teams that could not work on some days (warnings, never errors)
        "team_issues": team_issue_overview(inp),
    }
    plan.status = "ready"
    plan.computed_at = datetime.now(UTC)
    plan.error = None
    opts = dict(plan.options)
    opts.pop("needs_replan", None)
    plan.options = opts
    db.flush()
    if plan.is_active:
        apply_active(db, plan)
    return plan


def stop_costs(trip: SolvedTrip) -> list[dict[str, Any]]:
    """Allocate trip costs to stops: on-site labour by expected duration; drive costs by marginal detour."""
    u = trip.unit
    n = len(trip.stops)
    if n == 0:
        return []
    drive_cost = trip.distance_km * u.cost_km + trip.drive_min * (u.labour_cost_min + u.vehicle_cost_min)
    detours = []
    for s in trip.stops:
        detours.append(max(0.1, s.distance_from_prev_km))
    total = sum(detours)
    out = []
    for s, d in zip(trip.stops, detours, strict=True):
        onsite = s.predicted_min * (u.labour_cost_min + u.vehicle_cost_min)
        out.append(
            {
                "labour_onsite": round(s.predicted_min * u.labour_cost_min, 2),
                "vehicle_onsite": round(s.predicted_min * u.vehicle_cost_min, 2),
                "drive_share": round(drive_cost * d / total, 2),
                "direct": round(onsite + drive_cost * d / total, 2),
            }
        )
    return out


def write_results(
    db: Session,
    plan: Plan,
    inp: PlanningInput,
    res: SolveResult,
    kept: list[Tour],
    pack_results: dict[tuple[str, int], dict[str, Any]] | None = None,
) -> None:
    r = SettingsResolver(db, plan.tenant_id)
    overhead = float(r.get("costs.overhead_pct")) / 100
    surcharge = float(r.get("costs.overtime_surcharge_pct")) / 100
    cost_items = load_cost_items(db, plan.tenant_id)
    workdays = int(r.get("costs.workdays_per_month"))
    units_per_day: dict[date, int] = defaultdict(int)
    for k in {t.unit.key: t.unit.date for t in res.trips}.values():
        units_per_day[k] += 1
    kept_ids = {t.id for t in kept}
    old: dict[str, list[str]] = {}
    for t in db.scalars(select(Tour).where(Tour.plan_id == plan.id)):
        if t.id in kept_ids:
            continue
        old[f"{t.unit_key}#{t.trip_no}"] = [
            str(s.order_id)
            for s in db.scalars(select(TourStop).where(TourStop.tour_id == t.id).order_by(TourStop.position))
        ]
        db.delete(t)
    db.flush()
    by_unit: dict[str, list[SolvedTrip]] = defaultdict(list)
    for trip in res.trips:
        by_unit[trip.unit.key].append(trip)
    color_of: dict[str, str] = {}
    now = datetime.now(UTC)
    for key, trips in sorted(by_unit.items(), key=lambda kv: (kv[1][0].unit.date, kv[0])):
        trips.sort(key=lambda t: t.trip_no)
        unit = trips[0].unit
        vehicle_key = unit.vehicle.id
        color_of.setdefault(vehicle_key, PALETTE[len(color_of) % len(PALETTE)])
        day_end = trips[-1].end
        overtime_min = max(0, day_end - unit.end)
        for trip in trips:
            costs_per_stop = stop_costs(trip)
            labour = (trip.end - trip.start) * unit.labour_cost_min
            vehicle = trip.distance_km * unit.cost_km + (trip.end - trip.start) * unit.vehicle_cost_min
            ot = overtime_min * unit.labour_cost_min * surcharge if trip is trips[-1] else 0.0
            custom, custom_lines = trip_cost_items(
                cost_items,
                vehicle_ids={unit.vehicle.id} | ({unit.trailer.id} if unit.trailer else set()),
                staff_ids=[m.id for m in unit.members],
                km=trip.distance_km,
                minutes=trip.end - trip.start,
                plants=sum(len(s.stop.plants) for s in trip.stops),
                first_trip_of_day=trip is trips[0],
                units_that_day=units_per_day[unit.date],
                workdays_per_month=workdays,
            )
            shares = allocate_to_stops(
                custom_lines, [len(s.stop.plants) for s in trip.stops], [c["direct"] for c in costs_per_stop]
            )
            for c, share in zip(costs_per_stop, shares, strict=True):
                c["custom"] = share
                c["direct"] = round(c["direct"] + share, 2)
            pack = (pack_results or {}).get((key, trip.trip_no))
            tour = Tour(
                tenant_id=plan.tenant_id,
                plan_id=plan.id,
                date=unit.date,
                unit_key=key,
                trip_no=trip.trip_no,
                vehicle_id=None if unit.vehicle.virtual else uuid.UUID(unit.vehicle.id),
                trailer_id=uuid.UUID(unit.trailer.id) if unit.trailer and not unit.trailer.virtual else None,
                member_ids=[m.id for m in unit.members],
                driver_id=None if unit.driver.virtual else uuid.UUID(unit.driver.id),
                label=unit.label(),
                color=color_of[vehicle_key],
                start_min=trip.start,
                end_min=trip.end,
                distance_km=trip.distance_km,
                drive_min=trip.drive_min,
                service_min=sum(s.service_min for s in trip.stops),
                load={
                    "weight": round(sum(s.stop.weight for s in trip.stops), 1),
                    "area": round(sum(s.stop.area for s in trip.stops), 2),
                    "volume": round(sum(s.stop.volume for s in trip.stops), 2),
                    "plants": sum(len(s.stop.plants) for s in trip.stops),
                    "cap_weight": unit.cap_weight,
                    "cap_area": round(unit.cap_area, 2),
                    "cap_volume": round(unit.cap_volume, 2),
                },
                costs={
                    "labour": round(labour, 2),
                    "vehicle": round(vehicle, 2),
                    "overtime": round(ot, 2),
                    "custom": custom,
                    "custom_items": custom_lines,
                    "direct": round(labour + vehicle + ot + custom, 2),
                    "self_cost": round((labour + vehicle + ot + custom) * (1 + overhead), 2),
                    "overtime_min": overtime_min if trip is trips[-1] else 0,
                },
                breaks=list(trip.breaks),
                unit={
                    **unit.to_json(),
                    "members_detail": [
                        {
                            "id": m.id,
                            "solo_kg": m.solo_kg,
                            "carry_factor": m.carry_factor,
                            "hourly_cost": m.hourly_cost,
                            "licences": sorted(m.licences),
                        }
                        for m in unit.members
                    ],
                },
                warnings=[],
                load_status=("ok" if pack and pack["ok"] else "failed" if pack else "unknown"),
                load_message=pack.get("message") if pack else None,
            )
            new_orders = [s.stop.id for s in trip.stops]
            if f"{key}#{trip.trip_no}" in old and old[f"{key}#{trip.trip_no}"] != new_orders:
                tour.changed_at = now
            elif f"{key}#{trip.trip_no}" not in old and old:
                tour.changed_at = now
            db.add(tour)
            db.flush()
            for s, c in zip(trip.stops, costs_per_stop, strict=True):
                warnings = list(s.warnings)
                for a, b, d in s.stop.windows:
                    if d is None or d == unit.date:
                        if not (a <= s.start <= b):
                            warnings.append("time_window")
                        break
                db.add(
                    TourStop(
                        tenant_id=plan.tenant_id,
                        tour_id=tour.id,
                        order_id=s.stop.order.id,
                        position=s.position,
                        arrival_min=s.arrival,
                        start_min=s.start,
                        end_min=s.end,
                        service_min=s.service_min,
                        predicted_min=s.predicted_min,
                        team_size=unit.team_size,
                        drive_from_prev_min=s.drive_from_prev_min,
                        distance_from_prev_km=s.distance_from_prev_km,
                        experiment=s.stop.experiment,
                        costs=c,
                        warnings=warnings,
                    )
                )
            if pack and pack.get("placements") is not None:
                from app.packing.store import save_load_plan

                save_load_plan(db, tour, pack)
    db.flush()
    plan.unassigned = explain(inp, res.unassigned)
    plan.units = [u.to_json() for u in inp.units]
    plan.kpis = compute_kpis(db, plan, inp)


def compute_kpis(db: Session, plan: Plan, inp: PlanningInput | None = None) -> dict[str, Any]:
    tours = list(db.scalars(select(Tour).where(Tour.plan_id == plan.id)))
    stops = (
        list(db.scalars(select(TourStop).where(TourStop.tour_id.in_([t.id for t in tours])))) if tours else []
    )
    plants = 0
    by_order = {s.order_id for s in stops}
    if by_order:
        sources = {
            o.id: (o.return_of_id or o.id)
            for o in db.scalars(select(PickupOrder).where(PickupOrder.id.in_(by_order)))
        }
        from sqlalchemy import func

        plants = (
            db.scalar(
                select(func.count())
                .select_from(Plant)
                .where(Plant.order_id.in_(set(sources.values())), Plant.deleted_at.is_(None))
            )
            or 0
        )
    dates = sorted({t.date for t in tours})
    total_cost = sum(t.costs.get("self_cost", 0) for t in tours)
    labour_h = sum((t.end_min - t.start_min) * len(t.member_ids) for t in tours) / 60
    unit_days = {(t.unit_key) for t in tours}
    available = 0
    used = 0
    for key in unit_days:
        ts = [t for t in tours if t.unit_key == key]
        u = ts[0].unit
        available += max(1, u.get("end", 0) - u.get("start", 0))
        used += sum(t.end_min - t.start_min for t in ts)
    per_day = []
    for d in dates:
        ts = [t for t in tours if t.date == d]
        per_day.append(
            {
                "date": d.isoformat(),
                "units": len({t.unit_key for t in ts}),
                "trips": len(ts),
                "stops": sum(1 for s in stops if s.tour_id in {t.id for t in ts}),
                "km": round(sum(t.distance_km for t in ts), 1),
                "cost": round(sum(t.costs.get("self_cost", 0) for t in ts), 2),
            }
        )
    kpis = {
        "days_until_done": (dates[-1] - plan.start_date).days + 1 if dates else 0,
        "work_days": len(dates),
        "last_date": dates[-1].isoformat() if dates else None,
        "units": len(unit_days),
        "tours": len(tours),
        "stops_planned": len(stops),
        "stops_unassigned": len(plan.unassigned or []),
        "plants_planned": plants,
        "distance_km": round(sum(t.distance_km for t in tours), 1),
        "drive_hours": round(sum(t.drive_min for t in tours) / 60, 1),
        "labour_hours": round(labour_h, 1),
        "overtime_min": int(sum(t.costs.get("overtime_min", 0) for t in tours)),
        "total_cost": round(total_cost, 2),
        "cost_per_plant": round(total_cost / plants, 2) if plants else None,
        "utilisation_pct": round(used / available * 100, 1) if available else None,
        "load_failed": sum(1 for t in tours if t.load_status == "failed"),
        "per_day": per_day,
    }
    if inp is not None:
        kpis["units_available"] = len(inp.units)
    return kpis


def apply_active(db: Session, plan: Plan) -> None:
    """The active plan sets the order status and the cost coverage after planning."""
    r = SettingsResolver(db, plan.tenant_id)
    overhead = float(r.get("costs.overhead_pct")) / 100
    tours = {t.id: t for t in db.scalars(select(Tour).where(Tour.plan_id == plan.id))}
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id.in_(list(tours))))) if tours else []
    planned = {s.order_id: s for s in stops}
    for order in db.scalars(
        select(PickupOrder).where(
            PickupOrder.tenant_id == plan.tenant_id,
            PickupOrder.direction == plan.direction,
            PickupOrder.status.in_(("confirmed", "planned")),
            PickupOrder.deleted_at.is_(None),
        )
    ):
        est = dict(order.estimate or {})
        if order.id in planned:
            order.status = "planned"
            s = planned[order.id]
            self_cost = s.costs.get("direct", 0) * (1 + overhead)
            net = (est.get("price") or {}).get("net")
            est["plan_costs"] = {
                "self_cost": round(self_cost, 2),
                "coverage_pct": round(net / self_cost * 100, 1) if net and self_cost else None,
                "tour_date": tours[s.tour_id].date.isoformat(),
                "plan_id": str(plan.id),
                **s.costs,
            }
        else:
            if order.status == "planned":
                order.status = "confirmed"
            est.pop("plan_costs", None)
        order.estimate = est
    db.flush()


# ------------------------------------------------------------------------------- manual edits


def evaluate_tour(db: Session, tour: Tour) -> None:
    """Recompute times, load and warnings of a tour after a manual change."""
    from app.models.core import Tenant
    from app.models.orders import Address
    from app.routing.provider import provider_for
    from app.timemodel.estimate import Estimator

    est = Estimator(db, tour.tenant_id)
    tenant = db.get(Tenant, tour.tenant_id)
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == tour.id).order_by(TourStop.position)))
    unit = tour.unit
    members = unit.get("members_detail", [])
    solo = [m["solo_kg"] for m in members] or None
    factor = members[0]["carry_factor"] if members else None
    points = [(tenant.depot_lat, tenant.depot_lon)]
    orders = []
    for s in stops:
        o = db.get(PickupOrder, s.order_id)
        a = db.get(Address, o.address_id)
        points.append((a.lat, a.lon))
        orders.append(o)
    matrix = cached_matrix(db, provider_for(est.resolver), points) if len(points) > 1 else None
    df = unit.get("drive_factor", 1.0)
    t = tour.start_min
    weight = area = 0.0
    distance = drive = 0.0
    tour.warnings = []
    team = unit.get("team_size", len(tour.member_ids))
    for i, (s, o) in enumerate(zip(stops, orders, strict=True), start=1):
        tr = matrix.duration_min[i - 1][i] / df if matrix else 0
        dk = matrix.distance_km[i - 1][i] if matrix else 0
        paths = est.paths_for(o)
        plants = est.plants_of(o)
        calcs = [
            est.plant_calc(
                p, paths.get(p.access_path_id) or paths[None], solo_limits=solo, carry_factor=factor
            )
            for p in plants
        ]
        crew = max((c.crew.crew for c in calcs), default=1)
        predicted = est.stop_duration(calcs, team, unit.get("carry_speed", 1.0))
        service = predicted * est.quantile_factor + float(est.resolver.get("drive.parking_min"))
        s.position = i
        s.arrival_min = int(round(t + tr))
        s.start_min = s.arrival_min
        s.end_min = int(round(s.start_min + service))
        s.service_min = round(service, 1)
        s.predicted_min = round(predicted, 1)
        s.drive_from_prev_min = round(tr, 1)
        s.distance_from_prev_km = round(dk, 2)
        s.warnings = ["team_too_small"] if crew > team else []
        windows = o.time_windows or []
        for w in windows:
            if not w.get("date") or w.get("date") == tour.date.isoformat():
                if not (
                    int(w["from"][:2]) * 60 + int(w["from"][3:])
                    <= s.start_min
                    <= int(w["to"][:2]) * 60 + int(w["to"][3:])
                ):
                    s.warnings = s.warnings + ["time_window"]
                break
        if crew > team:
            tour.warnings = tour.warnings + [f"team_too_small:{o.number}"]
        t = s.end_min
        distance += dk
        drive += tr
        weight += sum(c.vars["weight"] for c in calcs)
        from app.timemodel.plantfill import footprint_m2

        area += sum(
            footprint_m2(p, float(est.resolver.get("packing.crown_overlap", *est.plant_chain(p))))
            for p in plants
        )
    back = (
        (matrix.duration_min[len(stops)][0] / df, matrix.distance_km[len(stops)][0])
        if matrix and stops
        else (0, 0)
    )
    tour.end_min = int(round(t + back[0]))
    tour.distance_km = round(distance + back[1], 2)
    tour.drive_min = round(drive + back[0], 1)
    tour.service_min = round(sum(s.service_min for s in stops), 1)
    load = dict(tour.load)
    load.update(
        {
            "weight": round(weight, 1),
            "area": round(area, 2),
            "plants": sum(len(est.plants_of(o)) for o in orders),
        }
    )
    tour.load = load
    if weight > unit.get("cap_weight", 1e9):
        tour.warnings = tour.warnings + ["overweight"]
    if area > unit.get("cap_area", 1e9):
        tour.warnings = tour.warnings + ["over_area"]
    if tour.end_min > unit.get("hard_end", 24 * 60):
        tour.warnings = tour.warnings + ["over_working_time"]
    elif tour.end_min > unit.get("end", 24 * 60):
        tour.warnings = tour.warnings + ["overtime"]
    labour = (tour.end_min - tour.start_min) * unit.get("labour_cost_min", 0)
    vehicle = tour.distance_km * unit.get("cost_km", 0) + (tour.end_min - tour.start_min) * unit.get(
        "vehicle_cost_min", 0
    )
    overhead = float(est.resolver.get("costs.overhead_pct")) / 100
    same_day = {
        t.unit_key
        for t in db.scalars(select(Tour).where(Tour.plan_id == tour.plan_id, Tour.date == tour.date))
    }
    custom, custom_lines = trip_cost_items(
        load_cost_items(db, tour.tenant_id),
        vehicle_ids={str(x) for x in (tour.vehicle_id, tour.trailer_id) if x}
        | {unit.get("vehicle_id")} - {None},
        staff_ids=[str(m) for m in tour.member_ids],
        km=tour.distance_km,
        minutes=tour.end_min - tour.start_min,
        plants=load.get("plants", 0) if isinstance(load, dict) else 0,
        first_trip_of_day=tour.trip_no == 1,
        units_that_day=max(1, len(same_day)),
        workdays_per_month=int(est.resolver.get("costs.workdays_per_month")),
    )
    ot = float(tour.costs.get("overtime", 0) or 0)
    tour.costs = {
        **tour.costs,
        "labour": round(labour, 2),
        "vehicle": round(vehicle, 2),
        "custom": custom,
        "custom_items": custom_lines,
        "direct": round(labour + vehicle + ot + custom, 2),
        "self_cost": round((labour + vehicle + ot + custom) * (1 + overhead), 2),
    }
    tour.changed_at = datetime.now(UTC)
    tour.load_status = "unknown"
    db.flush()


def move_stop(db: Session, stop: TourStop, target: Tour, position: int | None) -> list[Tour]:
    source = db.get(Tour, stop.tour_id)
    others = list(
        db.scalars(
            select(TourStop)
            .where(TourStop.tour_id == target.id, TourStop.id != stop.id)
            .order_by(TourStop.position)
        )
    )
    pos = len(others) + 1 if position is None else max(1, min(position, len(others) + 1))
    stop.tour_id = target.id
    seq = others[: pos - 1] + [stop] + others[pos - 1 :]
    for i, s in enumerate(seq, start=1):
        s.position = i
    db.flush()
    changed = [target]
    if source is not None and source.id != target.id:
        rest = list(
            db.scalars(select(TourStop).where(TourStop.tour_id == source.id).order_by(TourStop.position))
        )
        for i, s in enumerate(rest, start=1):
            s.position = i
        db.flush()
        if rest:
            evaluate_tour(db, source)
            changed.append(source)
        else:
            db.delete(source)
    evaluate_tour(db, target)
    return changed

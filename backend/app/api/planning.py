"""Tour planning API: plans, tours, manual moves, fixing, replanning, scenarios."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.jobs.queue import enqueue, run_now
from app.models.core import Job
from app.models.masterdata import Vehicle
from app.models.orders import Address, Customer, PickupOrder, Plant
from app.models.planning import Plan, Tour, TourStop
from app.planning.planner import apply_active, compute_kpis, move_stop
from app.settings.service import SettingsResolver

router = APIRouter(tags=["planning"])


class PlanIn(BaseModel):
    name: str | None = None
    start_date: date | None = None
    days: int | None = None
    direction: str = "pickup"
    time_limit_s: float | None = None
    order_ids: list[uuid.UUID] | None = None
    pack: bool = True
    sync: bool = False
    activate: bool = False


def plan_summary(p: Plan, job: Job | None = None) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "season": p.season,
        "direction": p.direction,
        "start_date": p.start_date,
        "days": p.days,
        "status": p.status,
        "is_active": p.is_active,
        "kind": p.kind,
        "parent_plan_id": p.parent_plan_id,
        "scenario": p.scenario,
        "kpis": p.kpis,
        "computed_at": p.computed_at,
        "created_at": p.created_at,
        "needs_replan": (p.options or {}).get("needs_replan", []),
        "error": (p.error or "").split("\n")[0] or None,
        "job": None
        if job is None
        else {"id": job.id, "status": job.status, "progress": job.progress, "message": job.message},
        "options": p.options,
    }


def _plan(db: Session, actor: Actor, plan_id: uuid.UUID) -> Plan:
    p = db.get(Plan, plan_id)
    if p is None or p.tenant_id != actor.tenant_id:
        raise NotFound("errors.plan_not_found")
    return p


def _start_job(db: Session, actor: Actor, plan: Plan, sync: bool) -> Job:
    plan.status = "computing"
    job = enqueue(
        db, "planning.solve", {"plan_id": str(plan.id)}, tenant_id=plan.tenant_id, created_by=actor.user_id
    )
    plan.job_id = job.id
    if sync:
        job = run_now(db, job)
        db.refresh(plan)
    return job


@router.get("/api/plans")
def list_plans(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("planning.read")
    rows = db.scalars(
        select(Plan)
        .where(Plan.tenant_id == actor.require_tenant(), Plan.kind == "plan")
        .order_by(Plan.created_at.desc())
        .limit(100)
    )
    jobs = {}
    out = []
    for p in rows:
        job = db.get(Job, p.job_id) if p.job_id else None
        jobs[p.id] = job
        out.append(plan_summary(p, job))
    return out


@router.post("/api/plans", status_code=201)
def create_plan(data: PlanIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    tid = actor.require_tenant()
    r = SettingsResolver(db, tid)
    start = data.start_date or date.today()
    days = data.days or int(r.get("planning.horizon_days"))
    season = start.year if start.month >= int(r.get("general.season_start_month")) else start.year - 1
    plan = Plan(
        tenant_id=tid,
        name=data.name or f"Plan ab {start.strftime('%d.%m.%Y')}",
        season=season,
        direction=data.direction if data.direction in ("pickup", "return") else "pickup",
        start_date=start,
        days=days,
        status="draft",
        kind="plan",
        created_by=actor.user_id,
        scenario={},
        options={
            k: v
            for k, v in {
                "time_limit_s": data.time_limit_s,
                "pack": data.pack,
                "order_ids": [str(x) for x in data.order_ids] if data.order_ids else None,
            }.items()
            if v is not None
        },
        kpis={},
        unassigned=[],
        units=[],
        solver={},
    )
    db.add(plan)
    db.flush()
    if (
        data.activate
        or db.scalar(
            select(Plan.id).where(
                Plan.tenant_id == tid, Plan.is_active.is_(True), Plan.direction == plan.direction
            )
        )
        is None
    ):
        plan.is_active = True
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="plan",
        entity_id=plan.id,
        action="create",
        new={"start": str(start), "days": days},
    )
    job = _start_job(db, actor, plan, data.sync)
    return plan_summary(plan, job)


def tour_dict(t: Tour, stops: list[dict[str, Any]], vehicle_name: str | None = None) -> dict[str, Any]:
    return {
        "id": t.id,
        "date": t.date,
        "unit_key": t.unit_key,
        "trip_no": t.trip_no,
        "vehicle_id": t.vehicle_id,
        "vehicle": vehicle_name or t.unit.get("vehicle"),
        "trailer": t.unit.get("trailer"),
        "members": t.unit.get("members", []),
        "driver_id": t.driver_id,
        "label": t.label,
        "color": t.color,
        "start_min": t.start_min,
        "end_min": t.end_min,
        "distance_km": t.distance_km,
        "drive_min": t.drive_min,
        "service_min": t.service_min,
        "load": t.load,
        "costs": t.costs,
        "breaks": t.breaks,
        "warnings": t.warnings,
        "fixed": t.fixed,
        "status": t.status,
        "changed_at": t.changed_at,
        "load_status": t.load_status,
        "load_message": t.load_message,
        "depot_start_min": t.depot_start_min,
        "depot_end_min": t.depot_end_min,
        "unload_min": t.unload_min,
        "unit": {
            k: t.unit.get(k)
            for k in (
                "start",
                "end",
                "hard_end",
                "team_size",
                "cap_weight",
                "cap_area",
                "cap_volume",
                "break_min",
                "virtual",
            )
        },
        "stops": stops,
    }


def plan_detail(db: Session, plan: Plan) -> dict[str, Any]:
    tours = list(
        db.scalars(
            select(Tour).where(Tour.plan_id == plan.id).order_by(Tour.date, Tour.unit_key, Tour.trip_no)
        )
    )
    stops = (
        list(
            db.scalars(
                select(TourStop)
                .where(TourStop.tour_id.in_([t.id for t in tours]))
                .order_by(TourStop.position)
            )
        )
        if tours
        else []
    )
    order_ids = {s.order_id for s in stops} | {
        uuid.UUID(u["order_id"]) for u in plan.unassigned or [] if u.get("order_id")
    }
    info: dict[uuid.UUID, dict[str, Any]] = {}
    if order_ids:
        rows = db.execute(
            select(PickupOrder, Customer.name, Address)
            .join(Customer, Customer.id == PickupOrder.customer_id)
            .join(Address, Address.id == PickupOrder.address_id)
            .where(PickupOrder.id.in_(order_ids))
        ).all()
        sources = {o.id: (o.return_of_id or o.id) for o, _, _ in rows}
        from sqlalchemy import func

        counts = dict(
            db.execute(
                select(Plant.order_id, func.count())
                .where(Plant.order_id.in_(set(sources.values())), Plant.deleted_at.is_(None))
                .group_by(Plant.order_id)
            ).all()
        )
        for o, name, a in rows:
            est = o.estimate or {}
            info[o.id] = {
                "order_id": o.id,
                "number": o.number,
                "customer": name,
                "street": a.street,
                "city": a.city,
                "lat": a.lat,
                "lon": a.lon,
                "plants": counts.get(sources[o.id], 0),
                "status": o.status,
                "team_size": est.get("team_size"),
                "weight": sum(p.get("weight", 0) for p in est.get("plants", [])),
                "time_windows": o.time_windows,
                "earliest_date": o.earliest_date,
                "latest_date": o.latest_date,
            }
    by_tour: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for s in stops:
        by_tour.setdefault(s.tour_id, []).append(
            {
                "id": s.id,
                "position": s.position,
                "arrival_min": s.arrival_min,
                "start_min": s.start_min,
                "end_min": s.end_min,
                "service_min": s.service_min,
                "predicted_min": s.predicted_min,
                "team_size": s.team_size,
                "fixed": s.fixed,
                "experiment": s.experiment,
                "status": s.status,
                "costs": s.costs,
                "warnings": s.warnings,
                "drive_from_prev_min": s.drive_from_prev_min,
                **info.get(s.order_id, {"order_id": s.order_id}),
            }
        )
    vehicles = {v.id: v.name for v in db.scalars(select(Vehicle).where(Vehicle.tenant_id == plan.tenant_id))}
    unassigned = [
        {**u, **{k: v for k, v in info.get(uuid.UUID(u["order_id"]), {}).items() if k != "order_id"}}
        for u in plan.unassigned or []
    ]
    job = db.get(Job, plan.job_id) if plan.job_id else None
    from app.models.core import Tenant

    tenant = db.get(Tenant, plan.tenant_id)
    return {
        **plan_summary(plan, job),
        "depot": {"lat": tenant.depot_lat, "lon": tenant.depot_lon, "name": tenant.name},
        "tours": [tour_dict(t, by_tour.get(t.id, []), vehicles.get(t.vehicle_id)) for t in tours],
        "unassigned": unassigned,
        "units": plan.units,
        "solver": plan.solver,
    }


@router.get("/api/plans/{plan_id}")
def get_plan(plan_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.read")
    return plan_detail(db, _plan(db, actor, plan_id))


@router.post("/api/plans/{plan_id}/activate")
def activate(plan_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    plan = _plan(db, actor, plan_id)
    if plan.kind != "plan":
        raise AppError("errors.validation")
    for other in db.scalars(
        select(Plan).where(
            Plan.tenant_id == plan.tenant_id, Plan.direction == plan.direction, Plan.is_active.is_(True)
        )
    ):
        other.is_active = False
    plan.is_active = True
    db.flush()
    apply_active(db, plan)
    audit.record(db, actor, tenant_id=plan.tenant_id, entity="plan", entity_id=plan.id, action="activate")
    return plan_summary(plan)


class ReplanIn(BaseModel):
    from_date: date | None = None
    sync: bool = False


@router.post("/api/plans/{plan_id}/replan")
def replan(plan_id: uuid.UUID, data: ReplanIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Plan again from a date on; earlier days, started tours and fixed parts stay."""
    actor.require("planning.write")
    plan = _plan(db, actor, plan_id)
    opts = dict(plan.options or {})
    opts["from_date"] = (data.from_date or max(date.today(), plan.start_date)).isoformat()
    plan.options = opts
    audit.record(
        db,
        actor,
        tenant_id=plan.tenant_id,
        entity="plan",
        entity_id=plan.id,
        action="replan",
        new={"from": opts["from_date"]},
    )
    job = _start_job(db, actor, plan, data.sync)
    return plan_summary(plan, job)


@router.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    plan = _plan(db, actor, plan_id)
    if plan.is_active:
        for order in db.scalars(
            select(PickupOrder).where(
                PickupOrder.tenant_id == plan.tenant_id, PickupOrder.status == "planned"
            )
        ):
            order.status = "confirmed"
    audit.record(db, actor, tenant_id=plan.tenant_id, entity="plan", entity_id=plan.id, action="delete")
    db.delete(plan)
    return {"ok": True}


class FixIn(BaseModel):
    fixed: bool


@router.patch("/api/tours/{tour_id}")
def fix_tour(tour_id: uuid.UUID, data: FixIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    tour = db.get(Tour, tour_id)
    if tour is None or tour.tenant_id != actor.tenant_id:
        raise NotFound()
    tour.fixed = data.fixed
    audit.record(
        db,
        actor,
        tenant_id=tour.tenant_id,
        entity="tour",
        entity_id=tour.id,
        action="fix" if data.fixed else "unfix",
    )
    return {"ok": True, "fixed": tour.fixed}


@router.patch("/api/tour-stops/{stop_id}")
def fix_stop(stop_id: uuid.UUID, data: FixIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    stop = db.get(TourStop, stop_id)
    if stop is None or stop.tenant_id != actor.tenant_id:
        raise NotFound()
    stop.fixed = data.fixed
    return {"ok": True, "fixed": stop.fixed}


class MoveIn(BaseModel):
    tour_id: uuid.UUID
    position: int | None = None


@router.post("/api/tour-stops/{stop_id}/move")
def move(stop_id: uuid.UUID, data: MoveIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Move a stop to another tour/position; times, loads, costs and warnings are recomputed at once."""
    actor.require("planning.write")
    stop = db.get(TourStop, stop_id)
    target = db.get(Tour, data.tour_id)
    if (
        stop is None
        or target is None
        or stop.tenant_id != actor.tenant_id
        or target.tenant_id != actor.tenant_id
    ):
        raise NotFound()
    source = db.get(Tour, stop.tour_id)
    if source.plan_id != target.plan_id:
        raise AppError("errors.validation")
    move_stop(db, stop, target, data.position)
    plan = db.get(Plan, target.plan_id)
    plan.kpis = compute_kpis(db, plan)
    if plan.is_active:
        apply_active(db, plan)
    audit.record(
        db,
        actor,
        tenant_id=plan.tenant_id,
        entity="tour_stop",
        entity_id=stop.id,
        action="move",
        old={"tour_id": str(source.id)},
        new={"tour_id": str(target.id), "position": stop.position},
    )
    return plan_detail(db, plan)


class UnassignIn(BaseModel):
    pass


@router.post("/api/tour-stops/{stop_id}/unassign")
def unassign(stop_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    stop = db.get(TourStop, stop_id)
    if stop is None or stop.tenant_id != actor.tenant_id:
        raise NotFound()
    tour = db.get(Tour, stop.tour_id)
    plan = db.get(Plan, tour.plan_id)
    order = db.get(PickupOrder, stop.order_id)
    db.delete(stop)
    db.flush()
    from app.planning.planner import evaluate_tour

    if db.scalar(select(TourStop.id).where(TourStop.tour_id == tour.id).limit(1)):
        evaluate_tour(db, tour)
    else:
        db.delete(tour)
    plan.unassigned = list(plan.unassigned or []) + [
        {"order_id": str(order.id), "number": order.number, "reason": "manual"}
    ]
    plan.kpis = compute_kpis(db, plan)
    if plan.is_active:
        apply_active(db, plan)
    return plan_detail(db, plan)


# ------------------------------------------------------------------------------- scenarios

PRESETS: dict[str, dict[str, Any]] = {
    "plus_person": {"add_staff": 1},
    "minus_person": {"remove_staff": 1},
    "plus_vehicle": {"add_vehicles_like": "largest"},
    "minus_vehicle": {"remove_vehicle_ids": "smallest"},
    "plus_day": {"days_delta": 1},
    "minus_day": {"days_delta": -1},
    "teams_of_3": {"team_size": 3},
}


class Variant(BaseModel):
    name: str | None = None
    preset: str | None = None
    scenario: dict[str, Any] = {}


class ScenariosIn(BaseModel):
    variants: list[Variant]
    time_limit_s: float | None = None
    sync: bool = False


def _resolve_scenario(db: Session, tenant_id: uuid.UUID, v: Variant) -> dict[str, Any]:
    sc = dict(PRESETS.get(v.preset or "", {}))
    sc.update(v.scenario or {})
    vehicles = list(
        db.scalars(
            select(Vehicle).where(
                Vehicle.tenant_id == tenant_id,
                Vehicle.deleted_at.is_(None),
                Vehicle.active.is_(True),
                Vehicle.kind != "trailer",
            )
        )
    )
    if sc.get("add_vehicles_like") == "largest" and vehicles:
        sc["add_vehicles_like"] = [str(max(vehicles, key=lambda x: x.payload_kg).id)]
    elif isinstance(sc.get("add_vehicles_like"), str):
        sc["add_vehicles_like"] = [sc["add_vehicles_like"]]
    if sc.get("remove_vehicle_ids") == "smallest" and vehicles:
        sc["remove_vehicle_ids"] = [str(min(vehicles, key=lambda x: x.payload_kg).id)]
    return sc


@router.post("/api/plans/{plan_id}/scenarios", status_code=201)
def create_scenarios(
    plan_id: uuid.UUID, data: ScenariosIn, actor: CurrentActor, db: DB
) -> list[dict[str, Any]]:
    """Run variants of a plan (±person, ±vehicle, ±day, other team size, free combinations)."""
    actor.require("scenarios.run")
    base = _plan(db, actor, plan_id)
    out = []
    for v in data.variants:
        sc = _resolve_scenario(db, base.tenant_id, v)
        opts = {k: val for k, val in (base.options or {}).items() if k not in ("from_date", "needs_replan")}
        opts["pack"] = False
        if data.time_limit_s:
            opts["time_limit_s"] = data.time_limit_s
        p = Plan(
            tenant_id=base.tenant_id,
            name=v.name or v.preset or "Variante",
            season=base.season,
            direction=base.direction,
            start_date=base.start_date,
            days=base.days,
            status="draft",
            kind="scenario",
            parent_plan_id=base.id,
            scenario={**sc, "preset": v.preset},
            options=opts,
            kpis={},
            unassigned=[],
            units=[],
            solver={},
            created_by=actor.user_id,
        )
        db.add(p)
        db.flush()
        job = _start_job(db, actor, p, data.sync)
        out.append(plan_summary(p, job))
    return out


def _delta(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None
    return round(b - a, 2)


@router.get("/api/plans/{plan_id}/scenarios")
def compare_scenarios(plan_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.read")
    base = _plan(db, actor, plan_id)
    variants = list(db.scalars(select(Plan).where(Plan.parent_plan_id == base.id).order_by(Plan.created_at)))
    keys = (
        "days_until_done",
        "work_days",
        "total_cost",
        "cost_per_plant",
        "stops_unassigned",
        "overtime_min",
        "distance_km",
        "labour_hours",
        "utilisation_pct",
    )
    bk = base.kpis or {}
    rows = []
    for v in variants:
        k = v.kpis or {}
        d = {key: _delta(bk.get(key), k.get(key)) for key in keys}
        marginal = {}
        if d.get("days_until_done") not in (None, 0) and d.get("total_cost") is not None:
            marginal["cost_per_day_saved"] = (
                round(-d["total_cost"] / d["days_until_done"], 2) if d["days_until_done"] < 0 else None
            )
            marginal["cost_per_day_added"] = (
                round(d["total_cost"] / d["days_until_done"], 2) if d["days_until_done"] > 0 else None
            )
        if d.get("stops_unassigned") not in (None, 0) and d.get("total_cost") is not None:
            marginal["cost_per_extra_stop"] = round(d["total_cost"] / -d["stops_unassigned"], 2)
        job = db.get(Job, v.job_id) if v.job_id else None
        rows.append({**plan_summary(v, job), "delta": d, "marginal": marginal})
    return {"base": plan_summary(base), "variants": rows, "presets": list(PRESETS)}


def mark_needs_replan(db: Session, tenant_id: uuid.UUID, reason: str, direction: str = "pickup") -> None:
    """Called when orders, staff or vehicles change: the active plan shows a replanning hint."""
    plan = db.scalar(
        select(Plan).where(Plan.tenant_id == tenant_id, Plan.is_active.is_(True), Plan.direction == direction)
    )
    if plan is None:
        return
    opts = dict(plan.options or {})
    reasons = list(opts.get("needs_replan", []))
    if reason not in reasons:
        reasons.append(reason)
    opts["needs_replan"] = reasons[-20:]
    plan.options = opts
    db.flush()


def cancel_stops_of_order(db: Session, order: PickupOrder) -> None:
    """A cancelled order leaves the active plan; affected tours are marked as changed."""
    for s in db.scalars(select(TourStop).where(TourStop.order_id == order.id)):
        tour = db.get(Tour, s.tour_id)
        plan = db.get(Plan, tour.plan_id) if tour else None
        if plan is None or not plan.is_active:
            continue
        db.delete(s)
        db.flush()
        from app.planning.planner import evaluate_tour

        if db.scalar(select(TourStop.id).where(TourStop.tour_id == tour.id).limit(1)):
            evaluate_tour(db, tour)
        else:
            db.delete(tour)
        tour.changed_at = datetime.now(UTC)
        plan.kpis = compute_kpis(db, plan)


def next_tours_for_dashboard(db: Session, tenant_id: uuid.UUID, limit: int = 6) -> list[dict[str, Any]]:
    plan = db.scalar(select(Plan).where(Plan.tenant_id == tenant_id, Plan.is_active.is_(True)))
    if plan is None:
        return []
    out = []
    for t in db.scalars(
        select(Tour)
        .where(Tour.plan_id == plan.id, Tour.date >= date.today() - timedelta(days=0))
        .order_by(Tour.date, Tour.start_min)
        .limit(limit)
    ):
        n = len(list(db.scalars(select(TourStop.id).where(TourStop.tour_id == t.id))))
        out.append(
            {
                "id": str(t.id),
                "date": t.date.isoformat(),
                "label": f"{t.date.strftime('%d.%m.')} · {t.label}",
                "stops": n,
            }
        )
    return out

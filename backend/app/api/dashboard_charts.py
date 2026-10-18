"""Charts and the logistics dashboard (package F): utilisation of staff and vehicles, tours over the
day, unloading windows at the depot, costs per day and per plant, accuracy of the time estimates,
today's and tomorrow's tours, open drafts, orders that could not be planned, costs of the week.
All figures come from the active plans (pickup and return); empty data gives empty lists."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.field import Measurement
from app.models.masterdata import StaffMember, Vehicle
from app.models.orders import Customer, Draft, PickupOrder
from app.models.planning import Plan, Tour, TourStop
from app.planning.availability import day_windows
from app.settings.service import SettingsResolver


def active_tours(
    db: Session, tenant_id: uuid.UUID, start: date | None = None, end: date | None = None
) -> list[Tour]:
    plans = [
        p.id for p in db.scalars(select(Plan).where(Plan.tenant_id == tenant_id, Plan.is_active.is_(True)))
    ]
    if not plans:
        return []
    q = select(Tour).where(Tour.plan_id.in_(plans))
    if start:
        q = q.where(Tour.date >= start)
    if end:
        q = q.where(Tour.date <= end)
    return list(db.scalars(q.order_by(Tour.date, Tour.start_min)))


def tour_summary(t: Tour, n_stops: int) -> dict[str, Any]:
    return {
        "id": t.id,
        "date": t.date,
        "trip_no": t.trip_no,
        "label": t.label,
        "vehicle": t.unit.get("vehicle"),
        "members": [m.get("name") for m in t.unit.get("members", [])],
        "color": t.color,
        "start_min": t.start_min,
        "end_min": t.end_min,
        "depot_start_min": t.depot_start_min,
        "depot_end_min": t.depot_end_min,
        "unload_min": t.unload_min,
        "stops": n_stops,
        "plants": (t.load or {}).get("plants", 0),
        "cost": (t.costs or {}).get("self_cost", 0),
        "status": t.status,
        "unit_key": t.unit_key,
    }


def _stop_counts(db: Session, tours: list[Tour]) -> dict[uuid.UUID, int]:
    counts: dict[uuid.UUID, int] = defaultdict(int)
    if tours:
        for s in db.scalars(select(TourStop).where(TourStop.tour_id.in_([t.id for t in tours]))):
            counts[s.tour_id] += 1
    return counts


def charts(db: Session, tenant_id: uuid.UUID, start: date, days: int, day: date | None) -> dict[str, Any]:
    end = start + timedelta(days=days - 1)
    tours = active_tours(db, tenant_id, start, end)
    counts = _stop_counts(db, tours)
    r = SettingsResolver(db, tenant_id)
    staff = list(
        db.scalars(
            select(StaffMember.id).where(
                StaffMember.tenant_id == tenant_id,
                StaffMember.deleted_at.is_(None),
                StaffMember.active.is_(True),
            )
        )
    )
    vehicles = list(
        db.scalars(
            select(Vehicle.id).where(
                Vehicle.tenant_id == tenant_id,
                Vehicle.deleted_at.is_(None),
                Vehicle.active.is_(True),
                Vehicle.kind != "trailer",
            )
        )
    )
    sw = day_windows(db, r, "staff", staff, start, end)
    vw = day_windows(db, r, "vehicle", vehicles, start, end)
    by_day: dict[date, list[Tour]] = defaultdict(list)
    for t in tours:
        by_day[t.date].append(t)
    utilisation, costs = [], []
    for i in range(days):
        d = start + timedelta(days=i)
        ts = by_day.get(d, [])
        staff_avail = sum(1 for s in staff if sw[s][d].available)
        veh_avail = sum(1 for v in vehicles if vw[v][d].available)
        staff_used = len({str(m) for t in ts for m in t.member_ids or [] if not str(m).startswith("virtual")})
        veh_used = len({t.vehicle_id for t in ts if t.vehicle_id})
        utilisation.append(
            {
                "date": d,
                "staff_used": staff_used,
                "staff_available": staff_avail,
                "staff_pct": round(staff_used / staff_avail * 100, 1) if staff_avail else None,
                "vehicles_used": veh_used,
                "vehicles_available": veh_avail,
                "vehicles_pct": round(veh_used / veh_avail * 100, 1) if veh_avail else None,
            }
        )
        cost = round(sum((t.costs or {}).get("self_cost", 0) for t in ts), 2)
        plants = sum((t.load or {}).get("plants", 0) for t in ts)
        costs.append(
            {
                "date": d,
                "cost": cost,
                "plants": plants,
                "cost_per_plant": round(cost / plants, 2) if plants else None,
            }
        )
    tour_days = sorted(by_day)
    if day is None or day not in by_day:
        today = date.today()
        day = next((d for d in tour_days if d >= today), tour_days[0] if tour_days else None)
    timeline = [tour_summary(t, counts[t.id]) for t in by_day.get(day, [])] if day else []
    windows = [
        {
            "tour_id": x["id"],
            "vehicle": x["vehicle"],
            "start": x["depot_start_min"],
            "end": x["depot_end_min"],
        }
        for x in timeline
        if x["depot_start_min"] is not None and x["depot_end_min"] is not None
    ]
    # how many vehicles are at the depot at the same time (per 15 minutes)
    load_curve = []
    if windows:
        lo = min(w["start"] for w in windows) // 15 * 15
        hi = max(w["end"] for w in windows)
        for m in range(lo, hi + 15, 15):
            load_curve.append({"min": m, "n": sum(1 for w in windows if w["start"] <= m < w["end"])})
    return {
        "start": start,
        "days": days,
        "utilisation": utilisation,
        "costs": costs,
        "tour_days": tour_days,
        "day": day,
        "timeline": timeline,
        "unload": {
            "windows": windows,
            "curve": load_curve,
            "max_parallel": max((c["n"] for c in load_curve), default=0),
        },
        "accuracy": accuracy(db, tenant_id),
    }


def accuracy(db: Session, tenant_id: uuid.UUID, weeks: int = 52) -> list[dict[str, Any]]:
    """Mean absolute percentage error of the predicted on-site time per calendar week. The prediction
    stored with the measurement is used; measurements without one (imported, synthetic) are predicted
    with the current formula."""
    since = date.today() - timedelta(weeks=weeks)
    rows = list(
        db.scalars(
            select(Measurement).where(
                Measurement.tenant_id == tenant_id,
                Measurement.excluded.is_(False),
                Measurement.duration_min > 0,
                Measurement.date >= since,
            )
        )
    )
    predicted = {m.id: m.predicted_min for m in rows}
    if any(v is None for v in predicted.values()):
        from app.learning.samples import prepare_samples
        from app.timemodel.estimate import Estimator

        est = Estimator(db, tenant_id)
        for sample in prepare_samples(db, tenant_id, est, include_excluded=False):
            mid = uuid.UUID(sample.measurement_id)
            if mid in predicted and predicted[mid] is None:
                predicted[mid] = sample.predict(est.time, est.time.params)
    by_week: dict[str, list[float]] = defaultdict(list)
    for m in rows:
        p = predicted.get(m.id)
        if p is None:
            continue
        y, w, _ = m.date.isocalendar()
        by_week[f"{y}-W{w:02d}"].append(abs(m.duration_min - p) / m.duration_min * 100)
    return [{"week": k, "mape": round(sum(v) / len(v), 1), "n": len(v)} for k, v in sorted(by_week.items())]


def logistics_overview(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Dashboard blocks: today/tomorrow, open drafts, unplannable orders, costs of the week."""
    from app.models.fleet import VehicleDraft

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    tours = active_tours(
        db, tenant_id, min(today, week_start), max(today + timedelta(days=1), week_start + timedelta(days=6))
    )
    counts = _stop_counts(db, tours)
    days = {
        key: {"date": d, "tours": [tour_summary(t, counts[t.id]) for t in tours if t.date == d]}
        for key, d in (("today", today), ("tomorrow", today + timedelta(days=1)))
    }
    week = [t for t in tours if week_start <= t.date <= week_start + timedelta(days=6)]
    week_cost = round(sum((t.costs or {}).get("self_cost", 0) for t in week), 2)
    week_plants = sum((t.load or {}).get("plants", 0) for t in week)
    unplanned = []
    for plan in db.scalars(select(Plan).where(Plan.tenant_id == tenant_id, Plan.is_active.is_(True))):
        for u in plan.unassigned or []:
            unplanned.append({**u, "direction": plan.direction, "plan_id": plan.id})
    ids = []
    for u in unplanned:
        try:
            ids.append(uuid.UUID(u["order_id"]))
        except (KeyError, ValueError):
            continue
    names = {}
    if ids:
        for o, c in db.execute(
            select(PickupOrder, Customer.name)
            .join(Customer, Customer.id == PickupOrder.customer_id)
            .where(PickupOrder.id.in_(ids))
        ).all():
            names[str(o.id)] = c
    return {
        **days,
        "open_drafts": {
            "orders": db.scalar(
                select(func.count())
                .select_from(Draft)
                .where(Draft.tenant_id == tenant_id, Draft.status.in_(("review", "processing", "failed")))
            )
            or 0,
            "vehicles": db.scalar(
                select(func.count())
                .select_from(VehicleDraft)
                .where(VehicleDraft.tenant_id == tenant_id, VehicleDraft.status == "open")
            )
            or 0,
        },
        "unplanned": [{**u, "customer": names.get(u.get("order_id"))} for u in unplanned[:12]],
        "unplanned_total": len(unplanned),
        "week": {
            "start": week_start,
            "cost": week_cost,
            "plants": week_plants,
            "cost_per_plant": round(week_cost / week_plants, 2) if week_plants else None,
            "tours": len(week),
        },
    }

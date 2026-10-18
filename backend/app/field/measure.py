"""Measurements from driver events.

Per stop: arrival -> carrying begins = fixed time, carrying begins -> loaded (pickup) or
delivered (return) = carrying time,
arrival -> loaded = on-site duration (what the time formula predicts). Breaks that fall into
an interval are subtracted. Drive time = arrival minus the previous departure (leave, depart,
shift start or unloading). With per-plant events the time of each plant is kept as well.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.field import Deviation, Measurement, TourEvent
from app.models.orders import PickupOrder
from app.models.planning import Tour, TourStop

DEPARTURES = ("leave", "depart", "shift_start", "unload")


def _minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def break_intervals(events: list[TourEvent]) -> list[tuple[datetime, datetime]]:
    out = []
    start: datetime | None = None
    for e in events:
        if e.kind == "break_start" and start is None:
            start = e.at
        elif e.kind == "break_end" and start is not None:
            out.append((start, e.at))
            start = None
    return out


def overlap_min(a: datetime, b: datetime, intervals: list[tuple[datetime, datetime]]) -> float:
    total = 0.0
    for s, e in intervals:
        lo, hi = max(a, s), min(b, e)
        if hi > lo:
            total += _minutes(lo, hi)
    return total


def build_measurement(db: Session, tour: Tour, stop: TourStop) -> Measurement | None:
    """Create or update the measurement of one stop from its events (None if incomplete)."""
    events = list(
        db.scalars(
            select(TourEvent)
            .where(TourEvent.tour_id == tour.id, TourEvent.voided.is_(False))
            .order_by(TourEvent.at, TourEvent.received_at)
        )
    )
    mine = [e for e in events if e.stop_id == stop.id]
    arrive = next((e for e in mine if e.kind == "arrive"), None)
    carry = next((e for e in mine if e.kind == "carry_start"), None)
    loaded = next((e for e in reversed(mine) if e.kind in ("loaded", "delivered")), None)
    leave = next((e for e in reversed(mine) if e.kind == "leave"), None)
    end = loaded or leave
    existing = db.scalar(select(Measurement).where(Measurement.stop_id == stop.id))
    if arrive is None or end is None or end.at <= arrive.at:
        return existing
    breaks = break_intervals(events)
    brk = overlap_min(arrive.at, end.at, breaks)
    duration = max(0.0, _minutes(arrive.at, end.at) - brk)
    fixed = carry_min = None
    per_plant: list[dict[str, Any]] = []
    if carry is not None and arrive.at <= carry.at <= end.at:
        fixed = max(0.0, _minutes(arrive.at, carry.at) - overlap_min(arrive.at, carry.at, breaks))
        carry_min = max(0.0, _minutes(carry.at, end.at) - overlap_min(carry.at, end.at, breaks))
        prev = carry.at
        for e in mine:
            if e.kind == "plant_done" and e.plant_id and carry.at <= e.at <= end.at:
                minutes = max(0.0, _minutes(prev, e.at) - overlap_min(prev, e.at, breaks))
                per_plant.append({"plant_id": str(e.plant_id), "minutes": round(minutes, 2)})
                prev = e.at
    before = [e for e in events if e.kind in DEPARTURES and e.at <= arrive.at and e.stop_id != stop.id]
    drive = None
    if before:
        last = before[-1]
        drive = max(0.0, _minutes(last.at, arrive.at) - overlap_min(last.at, arrive.at, breaks))
    order = db.get(PickupOrder, stop.order_id)
    est = (order.estimate or {}) if order else {}
    features = {
        "n_plants": len(est.get("plants", [])),
        "total_weight": round(sum(p.get("weight", 0) or 0 for p in est.get("plants", [])), 1),
        "team_needed": est.get("team_size"),
    }
    m = existing or Measurement(
        tenant_id=tour.tenant_id, order_id=stop.order_id, stop_id=stop.id, source="app"
    )
    m.tour_id = tour.id
    m.date = tour.date
    m.team_size = max(1, len(tour.member_ids or []))
    m.member_ids = list(tour.member_ids or [])
    m.duration_min = round(duration, 2)
    m.fixed_min = round(fixed, 2) if fixed is not None else None
    m.carry_min = round(carry_min, 2) if carry_min is not None else None
    m.drive_min = round(drive, 2) if drive is not None else None
    m.break_min = round(brk, 2)
    m.per_plant = per_plant
    m.predicted_min = stop.predicted_min
    m.experiment = bool(stop.experiment)
    m.features = features
    m.deviations = len(list(db.scalars(select(Deviation.id).where(Deviation.stop_id == stop.id))))
    if existing is None:
        db.add(m)
    db.flush()
    return m

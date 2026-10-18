"""Apply events from the driver app (idempotent per client_id, safe to resend after being offline)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.field.measure import build_measurement
from app.models.field import EVENT_KINDS, TourEvent
from app.models.orders import Photo, PickupOrder
from app.models.packing import LoadPlacement, LoadPlan
from app.models.planning import Tour, TourStop
from app.settings.service import SettingsResolver

STOP_KINDS = {"arrive", "carry_start", "plant_done", "loaded", "delivered", "leave", "qr_scan"}
STOP_STATUS = {
    "arrive": "arrived",
    "carry_start": "carrying",
    "loaded": "loaded",
    "delivered": "delivered",
    "leave": "done",
}
STATUS_RANK = {
    "planned": 0,
    "arrived": 1,
    "carrying": 2,
    "loaded": 3,
    "delivered": 3,
    "done": 4,
    "skipped": 4,
}
PROOF_KINDS = ("loaded", "delivered")


class EventError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_member(actor: Actor, tour: Tour) -> bool:
    return actor.staff_member_id is not None and str(actor.staff_member_id) in {
        str(m) for m in tour.member_ids or []
    }


def can_use_tour(actor: Actor, tour: Tour) -> bool:
    if tour.tenant_id != actor.tenant_id:
        return False
    return is_member(actor, tour) or actor.has("planning.write")


def photo_by_client_id(db: Session, tenant_id: uuid.UUID, client_id: str | None) -> Photo | None:
    if not client_id:
        return None
    return db.scalar(select(Photo).where(Photo.tenant_id == tenant_id, Photo.client_id == client_id))


def apply_event(db: Session, actor: Actor, raw: dict[str, Any], settings: SettingsResolver) -> TourEvent:
    client_id = str(raw.get("client_id") or "")[:64]
    if not client_id:
        raise EventError("errors.event_client_id")
    existing = db.scalar(
        select(TourEvent).where(TourEvent.tenant_id == actor.tenant_id, TourEvent.client_id == client_id)
    )
    if existing is not None:
        return existing  # resent after a lost answer: nothing to do
    kind = raw.get("kind")
    if kind not in EVENT_KINDS:
        raise EventError("errors.event_kind")
    try:
        tour = db.get(Tour, uuid.UUID(str(raw.get("tour_id"))))
    except ValueError:
        tour = None
    if tour is None or not can_use_tour(actor, tour):
        raise EventError("errors.not_found")
    try:
        at = datetime.fromisoformat(str(raw.get("at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventError("errors.event_time") from exc
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if at > now + timedelta(minutes=10) or at < now - timedelta(days=30):
        raise EventError("errors.event_time")
    stop: TourStop | None = None
    if kind in STOP_KINDS:
        try:
            stop = db.get(TourStop, uuid.UUID(str(raw.get("stop_id"))))
        except ValueError:
            stop = None
        if stop is None or stop.tour_id != tour.id:
            raise EventError("errors.event_stop")
    plant_id = None
    if raw.get("plant_id"):
        try:
            plant_id = uuid.UUID(str(raw["plant_id"]))
        except ValueError as exc:
            raise EventError("errors.event_plant") from exc
    if kind in ("plant_done", "qr_scan") and plant_id is None:
        raise EventError("errors.event_plant")
    photo = None
    if raw.get("photo_id"):
        try:
            photo = db.get(Photo, uuid.UUID(str(raw["photo_id"])))
        except ValueError:
            photo = None
    photo = photo or photo_by_client_id(db, actor.tenant_id, raw.get("photo_client_id"))
    if photo is not None and photo.tenant_id != actor.tenant_id:
        photo = None
    if kind in PROOF_KINDS and bool(settings.get("driver.require_pickup_photo")) and photo is None:
        raise EventError("errors.event_photo_required")
    ev = TourEvent(
        tenant_id=actor.tenant_id,
        client_id=client_id,
        tour_id=tour.id,
        stop_id=stop.id if stop else None,
        plant_id=plant_id,
        kind=kind,
        at=at,
        user_id=actor.user_id,
        staff_id=actor.staff_member_id,
        photo_id=photo.id if photo else None,
        lat=raw.get("lat"),
        lon=raw.get("lon"),
        data={k: v for k, v in (raw.get("data") or {}).items() if isinstance(k, str)},
    )
    db.add(ev)
    db.flush()
    # status of stop and tour
    if tour.status == "planned":
        tour.status = "in_progress"
    if stop is not None and kind in STOP_STATUS:
        new = STOP_STATUS[kind]
        if STATUS_RANK.get(new, 0) >= STATUS_RANK.get(stop.status, 0):
            stop.status = new
        if kind in ("loaded", "delivered", "leave"):
            order = db.get(PickupOrder, stop.order_id)
            if order is not None and order.status in ("planned", "confirmed"):
                order.status = "picked_up" if order.direction == "pickup" else "returned"
                if order.direction == "return" and order.return_of_id:
                    pickup = db.get(PickupOrder, order.return_of_id)
                    if pickup is not None and pickup.status in ("picked_up", "stored"):
                        pickup.status = "returned"  # the plants are back home
    if photo is not None and stop is not None:
        photo.stop_id = photo.stop_id or stop.id
        photo.order_id = photo.order_id or stop.order_id
    if kind == "qr_scan":
        lp = db.scalar(select(LoadPlan).where(LoadPlan.tour_id == tour.id))
        if lp is not None:
            place = db.scalar(
                select(LoadPlacement).where(
                    LoadPlacement.load_plan_id == lp.id, LoadPlacement.plant_id == plant_id
                )
            )
            if place is not None:
                place.loaded_at = at
    if kind == "shift_end":
        tour.status = "done"
    if stop is not None and kind in ("loaded", "delivered", "leave"):
        build_measurement(db, tour, stop)
    if kind == "unload_done":
        build_unload_measurement(db, tour, ev)
    return ev


def build_unload_measurement(db: Session, tour: Tour, done: TourEvent) -> None:
    """Unloading begins -> finished at the depot = one measurement for the formula "unload"."""
    from app.models.field import UnloadMeasurement
    from app.planning.inputs import plant_weight
    from app.timemodel.estimate import Estimator

    start = db.scalar(
        select(TourEvent)
        .where(
            TourEvent.tour_id == tour.id,
            TourEvent.kind == "unload_start",
            TourEvent.voided.is_(False),
            TourEvent.at <= done.at,
        )
        .order_by(TourEvent.at.desc())
        .limit(1)
    )
    if start is None:
        return
    minutes = (done.at - start.at).total_seconds() / 60
    if minutes <= 0 or minutes > 6 * 60:
        return
    est = Estimator(db, tour.tenant_id)
    weights: list[float] = []
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == tour.id)))
    for st in stops:
        order = db.get(PickupOrder, st.order_id)
        if order is not None:
            weights += [plant_weight(p) for p in est.plants_of(order)]
    m = db.scalar(select(UnloadMeasurement).where(UnloadMeasurement.tour_id == tour.id))
    if m is None:
        m = UnloadMeasurement(tenant_id=tour.tenant_id, tour_id=tour.id, source="app")
        db.add(m)
    m.date = tour.date
    m.team_size = max(1, len(tour.member_ids or []))
    m.n_plants = len(weights)
    m.total_weight = round(sum(weights), 1)
    m.n_stops = max(1, len(stops))
    m.weights = [round(w, 1) for w in weights]
    m.minutes = round(minutes, 1)
    m.predicted_min = tour.unload_min
    db.flush()


def apply_events(db: Session, actor: Actor, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each event is applied on its own (savepoint): one bad event does not block the queue."""
    settings = SettingsResolver(db, actor.tenant_id)
    results = []
    touched: set[uuid.UUID] = set()
    for raw in sorted(events, key=lambda e: str(e.get("at"))):
        sp = db.begin_nested()
        try:
            ev = apply_event(db, actor, raw, settings)
            sp.commit()
            touched.add(ev.tour_id)
            results.append({"client_id": raw.get("client_id"), "ok": True, "id": str(ev.id)})
        except EventError as exc:
            sp.rollback()
            results.append({"client_id": raw.get("client_id"), "ok": False, "error": exc.code})
    if touched:
        audit.record(
            db,
            actor,
            tenant_id=actor.tenant_id,
            entity="tour_events",
            entity_id=None,
            action="sync",
            new={"events": sum(1 for r in results if r["ok"]), "tours": [str(t) for t in touched]},
        )
    return results

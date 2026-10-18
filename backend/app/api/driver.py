"""Driver app API: own tours of the day (offline package), events, photos, deviation reports."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.api.files import IMAGE_TYPES, photo_dict, save_photo
from app.api.loading import _tour_head
from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.core.modules import module_enabled
from app.field.events import apply_events, can_use_tour, photo_by_client_id
from app.models.field import DEVIATION_KINDS, Deviation, TourEvent
from app.models.masterdata import StaffMember, StorageArea, Vehicle
from app.models.orders import AccessPath, Address, Customer, PathSegment, Photo, PickupOrder, Plant
from app.models.planning import Plan, Tour, TourStop
from app.packing.store import load_plan_dict
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import geometry

router = APIRouter(prefix="/api/driver", tags=["driver"])


def _require_driver(actor: Actor) -> None:
    actor.require_tenant()
    if not (actor.has("driver.app") or actor.has("planning.read")):
        actor.require("driver.app")


def nav_links(a: Address | None) -> dict[str, str]:
    if a is None:
        return {}
    if a.lat is not None and a.lon is not None:
        dest = f"{a.lat:.6f},{a.lon:.6f}"
    else:
        dest = f"{a.street}, {a.postal_code} {a.city}".replace(" ", "+")
    return {
        "google": f"https://www.google.com/maps/dir/?api=1&destination={dest}",
        "apple": f"https://maps.apple.com/?daddr={dest}",
    }


@router.get("/me")
def me(actor: CurrentActor, db: DB) -> dict[str, Any]:
    _require_driver(actor)
    r = SettingsResolver(db, actor.tenant_id)
    staff = db.get(StaffMember, actor.staff_member_id) if actor.staff_member_id else None
    return {
        "name": staff.name if staff else actor.label,
        "staff_id": actor.staff_member_id,
        "settings": {
            "per_plant_events": bool(r.get("driver.per_plant_events")),
            "require_pickup_photo": bool(r.get("driver.require_pickup_photo")),
            "qr_module": bool(r.get("driver.qr_module")),
        },
    }


def _photos(db, **where) -> list[dict[str, Any]]:
    q = select(Photo)
    for k, v in where.items():
        q = q.where(getattr(Photo, k) == v)
    return [
        {"id": p.id, "url": f"/api/files/{p.file_id}", "kind": p.kind, "caption": p.caption}
        for p in db.scalars(q.order_by(Photo.position, Photo.created_at))
    ]


def _storage_name(db, area_id) -> str | None:
    if area_id is None:
        return None
    a = db.get(StorageArea, area_id)
    return a.name if a else None


def stop_package(db, stop: TourStop) -> dict[str, Any]:
    order = db.get(PickupOrder, stop.order_id)
    customer = db.get(Customer, order.customer_id) if order else None
    address = db.get(Address, order.address_id) if order else None
    source = (order.return_of_id or order.id) if order else stop.order_id
    est = (order.estimate or {}) if order else {}
    crew = {p["id"]: p for p in est.get("plants", [])}
    storage_on = module_enabled(db, stop.tenant_id, "storage")
    plants = []
    for p in db.scalars(
        select(Plant).where(Plant.order_id == source, Plant.deleted_at.is_(None)).order_by(Plant.number)
    ):
        g = geometry(p)
        c = crew.get(str(p.id), {})
        plants.append(
            {
                "id": p.id,
                "number": p.number,
                "name": p.species_name or p.label or "",
                "label": p.label,
                "pot_d": round(g.pot_d),
                "pot_h": round(g.pot_h),
                "height": round(g.total_h),
                "crown_w": round(g.crown_w),
                "weight": p.weight_measured_kg or p.weight_kg,
                "crew": c.get("crew"),
                "equipment": c.get("equipment"),
                "can_tilt": p.can_tilt,
                "sensitive": p.sensitive,
                "must_secure": p.must_secure,
                "notes": p.notes,
                "storage": _storage_name(db, p.storage_area_id) if storage_on else None,
                "photos": _photos(db, plant_id=p.id),
            }
        )
    paths = []
    for ap in db.scalars(
        select(AccessPath).where(AccessPath.order_id == source).order_by(AccessPath.created_at)
    ):
        segs = list(
            db.scalars(select(PathSegment).where(PathSegment.path_id == ap.id).order_by(PathSegment.position))
        )
        paths.append(
            {
                "id": ap.id,
                "name": ap.name,
                "notes": ap.notes,
                "length_m": ap.length_confirmed_m or sum(s.length_m or 0 for s in segs),
                "segments": [
                    {
                        "kind": s.kind,
                        "length_m": s.length_m,
                        "steps": s.steps,
                        "min_width_cm": s.min_width_cm,
                        "surface": s.surface,
                        "slope_pct": s.slope_pct,
                        "elevator": s.elevator,
                        "notes": s.notes,
                    }
                    for s in segs
                ],
                "photos": _photos(db, path_id=ap.id),
            }
        )
    return {
        "id": stop.id,
        "position": stop.position,
        "status": stop.status,
        "arrival_min": stop.arrival_min,
        "start_min": stop.start_min,
        "end_min": stop.end_min,
        "team_size": stop.team_size,
        "predicted_min": stop.predicted_min,
        "experiment": stop.experiment,
        "order": {"id": order.id, "number": order.number, "notes": order.notes, "direction": order.direction}
        if order
        else None,
        "customer": {
            "name": customer.name,
            "phone": customer.phone,
            "notes": customer.notes,
            "preferred_contact": customer.preferred_contact,
        }
        if customer
        else None,
        "address": {
            "street": address.street,
            "postal_code": address.postal_code,
            "city": address.city,
            "lat": address.lat,
            "lon": address.lon,
            "parking_notes": address.parking_notes,
            "bell_notes": address.bell_notes,
            "access_notes": address.access_notes,
        }
        if address
        else None,
        "nav": nav_links(address),
        "plants": plants,
        "paths": paths,
        "equipment": sorted({p["equipment"] for p in plants if p.get("equipment")}),
        "proof_photos": _photos(db, stop_id=stop.id, kind="pickup_proof")
        + _photos(db, stop_id=stop.id, kind="delivery_proof"),
    }


def tour_package(db, tour: Tour) -> dict[str, Any]:
    vehicle = db.get(Vehicle, tour.vehicle_id) if tour.vehicle_id else None
    trailer = db.get(Vehicle, tour.trailer_id) if tour.trailer_id else None
    members = []
    for m in tour.member_ids or []:
        s = db.get(StaffMember, uuid.UUID(str(m)))
        if s is not None:
            members.append(
                {"id": s.id, "name": s.name, "phone": s.phone, "driver": str(s.id) == str(tour.driver_id)}
            )
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == tour.id).order_by(TourStop.position)))
    events = list(
        db.scalars(
            select(TourEvent)
            .where(TourEvent.tour_id == tour.id, TourEvent.voided.is_(False))
            .order_by(TourEvent.at)
        )
    )
    return {
        "id": tour.id,
        "date": tour.date,
        "label": tour.label,
        "trip_no": tour.trip_no,
        "color": tour.color,
        "status": tour.status,
        "start_min": tour.start_min,
        "end_min": tour.end_min,
        "depot_start_min": tour.depot_start_min,
        "depot_end_min": tour.depot_end_min,
        "breaks": tour.breaks,
        "distance_km": tour.distance_km,
        "vehicle": {"name": vehicle.name, "plate": vehicle.plate}
        if vehicle
        else {"name": tour.unit.get("vehicle")},
        "trailer": {"name": trailer.name, "plate": trailer.plate} if trailer else None,
        "members": members,
        "stops": [stop_package(db, s) for s in stops],
        "events": [
            {
                "client_id": e.client_id,
                "kind": e.kind,
                "stop_id": e.stop_id,
                "plant_id": e.plant_id,
                "at": e.at,
            }
            for e in events
        ],
        "load": {"tour": _tour_head(db, tour), "plan": load_plan_dict(db, tour)},
    }


@router.get("/day")
def day(actor: CurrentActor, db: DB, on: date | None = None, days: int = 1) -> dict[str, Any]:
    """Own tours of the active plan for one or more days (everything the app needs offline)."""
    _require_driver(actor)
    start = on or datetime.now(UTC).date()
    days = max(1, min(days, 7))
    tours = list(
        db.scalars(
            select(Tour)
            .join(Plan, Plan.id == Tour.plan_id)
            .where(
                Tour.tenant_id == actor.tenant_id,
                Plan.is_active.is_(True),
                Tour.date >= start,
                Tour.date < start + timedelta(days=days),
            )
            .order_by(Tour.date, Tour.start_min, Tour.trip_no)
        )
    )
    mine = [
        t
        for t in tours
        if can_use_tour(actor, t)
        and (
            actor.staff_member_id is None
            or str(actor.staff_member_id) in {str(m) for m in t.member_ids or []}
        )
    ]
    return {
        "from": start,
        "days": days,
        "generated_at": datetime.now(UTC),
        "tours": [tour_package(db, t) for t in mine],
    }


class EventsIn(BaseModel):
    events: list[dict[str, Any]] = Field(max_length=500)


@router.post("/events")
def post_events(data: EventsIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _require_driver(actor)
    results = apply_events(db, actor, data.events)
    return {
        "results": results,
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
    }


@router.post("/photos", status_code=201)
async def upload(
    actor: CurrentActor,
    db: DB,
    file: UploadFile = File(...),
    client_id: str = Form(...),
    kind: str = Form("pickup_proof"),
    stop_id: uuid.UUID = Form(...),
    plant_id: uuid.UUID | None = Form(None),
    caption: str | None = Form(None),
) -> dict[str, Any]:
    """Photo from the app (pickup proof, damage, path). Sent again after a lost answer: same photo."""
    _require_driver(actor)
    existing = photo_by_client_id(db, actor.tenant_id, client_id)
    if existing is not None:
        return photo_dict(existing)
    stop = db.get(TourStop, stop_id)
    tour = db.get(Tour, stop.tour_id) if stop else None
    if stop is None or tour is None or not can_use_tour(actor, tour):
        raise NotFound()
    if file.content_type not in IMAGE_TYPES:
        raise AppError("errors.file_type")
    raw = await file.read()
    if len(raw) > get_config().max_upload_mb * 1024 * 1024:
        raise AppError("errors.file_too_large", status_code=413)
    if kind not in ("pickup_proof", "delivery_proof", "damage", "path_segment", "plant_front", "other"):
        kind = "other"
    photo = save_photo(
        db,
        actor,
        raw,
        file.filename or "foto.jpg",
        kind,
        order_id=stop.order_id,
        plant_id=plant_id,
        stop_id=stop.id,
        caption=caption,
    )
    photo.client_id = client_id[:64]
    db.flush()
    return photo_dict(photo)


class DeviationIn(BaseModel):
    client_id: str = Field(min_length=4, max_length=64)
    tour_id: uuid.UUID
    stop_id: uuid.UUID
    plant_id: uuid.UUID | None = None
    kind: str
    note: str | None = Field(default=None, max_length=2000)
    values: dict[str, Any] = Field(default_factory=dict)
    photo_client_ids: list[str] = Field(default_factory=list, max_length=10)
    at: datetime | None = None


@router.post("/deviations", status_code=201)
def report_deviation(data: DeviationIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _require_driver(actor)
    existing = db.scalar(
        select(Deviation).where(Deviation.tenant_id == actor.tenant_id, Deviation.client_id == data.client_id)
    )
    if existing is not None:
        return deviation_dict(db, existing)
    if data.kind not in DEVIATION_KINDS:
        raise AppError("errors.validation", detail="kind")
    tour = db.get(Tour, data.tour_id)
    stop = db.get(TourStop, data.stop_id)
    if tour is None or stop is None or stop.tour_id != tour.id or not can_use_tour(actor, tour):
        raise NotFound()
    values = {
        k: v
        for k, v in data.values.items()
        if k
        in (
            "weight_kg",
            "height_cm",
            "crown_width_cm",
            "pot_diameter_cm",
            "path_length_m",
            "steps",
            "min_width_cm",
        )
        and isinstance(v, (int, float))
    }
    photos = [
        p.id for c in data.photo_client_ids if (p := photo_by_client_id(db, actor.tenant_id, c)) is not None
    ]
    dev = Deviation(
        tenant_id=actor.tenant_id,
        client_id=data.client_id,
        tour_id=tour.id,
        stop_id=stop.id,
        order_id=stop.order_id,
        plant_id=data.plant_id,
        kind=data.kind,
        note=data.note,
        values=values,
        photo_ids=[str(p) for p in photos],
        reported_by=actor.user_id,
        staff_id=actor.staff_member_id,
        reported_at=data.at or datetime.now(UTC),
    )
    db.add(dev)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="deviation",
        entity_id=dev.id,
        action="report",
        new={"kind": dev.kind, "order_id": str(dev.order_id)},
    )
    return deviation_dict(db, dev)


def deviation_dict(db, d: Deviation) -> dict[str, Any]:
    order = db.get(PickupOrder, d.order_id)
    plant = db.get(Plant, d.plant_id) if d.plant_id else None
    staff = db.get(StaffMember, d.staff_id) if d.staff_id else None
    photos = [db.get(Photo, uuid.UUID(p)) for p in d.photo_ids or []]
    return {
        "id": d.id,
        "client_id": d.client_id,
        "kind": d.kind,
        "status": d.status,
        "note": d.note,
        "values": d.values,
        "order_id": d.order_id,
        "order_number": order.number if order else None,
        "tour_id": d.tour_id,
        "stop_id": d.stop_id,
        "plant_id": d.plant_id,
        "plant_number": plant.number if plant else None,
        "plant": {
            "weight_kg": plant.weight_measured_kg or plant.weight_kg,
            "height_cm": plant.total_height_cm,
            "crown_width_cm": plant.crown_width_cm,
            "pot_diameter_cm": plant.pot_diameter_cm,
        }
        if plant
        else None,
        "reported_by": staff.name if staff else None,
        "reported_at": d.reported_at or d.created_at,
        "photos": [{"id": p.id, "url": f"/api/files/{p.file_id}"} for p in photos if p is not None],
        "decided_at": d.decided_at,
    }

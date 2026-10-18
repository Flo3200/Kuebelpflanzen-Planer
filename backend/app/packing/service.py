"""Builds packer input from the database, couples the packer with the tour planner."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.i18n import t
from app.models.masterdata import Species, Vehicle, VehicleShelf
from app.models.orders import PickupOrder, Plant
from app.models.planning import Tour, TourStop
from app.packing.geometry import Box, PlantItem, Shelf, Space
from app.packing.packer import Packer, PackResult, PackSettings
from app.settings.service import SettingsResolver
from app.timemodel.knowledge import DEFAULTS
from app.timemodel.plantfill import geometry


def space_from_vehicle(db: Session, v: Vehicle) -> Space:
    obstacles = []
    if v.wheel_arch_length_cm and v.wheel_arch_width_cm and v.wheel_arch_x_cm is not None:
        x0, x1 = v.wheel_arch_x_cm, v.wheel_arch_x_cm + v.wheel_arch_length_cm
        h = v.wheel_arch_height_cm or 30
        obstacles.append(Box(x0, 0, x1, v.wheel_arch_width_cm, h))
        obstacles.append(Box(x0, v.cargo_width_cm - v.wheel_arch_width_cm, x1, v.cargo_width_cm, h))
    shelves = [
        Shelf(
            str(s.id),
            s.name,
            s.x_cm,
            s.y_cm,
            s.length_cm,
            s.depth_cm,
            s.height_cm,
            s.clearance_cm,
            s.max_load_kg,
            s.blocks_floor,
        )
        for s in db.scalars(select(VehicleShelf).where(VehicleShelf.vehicle_id == v.id))
    ]
    is_trailer = v.kind == "trailer"
    return Space(
        id=str(v.id),
        name=v.name,
        kind=v.kind,
        length=v.cargo_length_cm,
        width=v.cargo_width_cm,
        height=v.cargo_height_cm,
        door_w=v.door_width_cm,
        door_h=v.door_height_cm,
        payload=v.payload_kg,
        obstacles=obstacles,
        shelves=shelves,
        front_axle_x=None if is_trailer else v.front_axle_x_cm,
        rear_axle_x=v.rear_axle_x_cm,
        max_front_extra=v.max_front_axle_extra_kg,
        max_rear_extra=v.max_rear_axle_extra_kg,
        hitch_x=v.hitch_x_cm if is_trailer else None,
        max_tongue=v.max_tongue_load_kg,
        min_tongue=v.min_tongue_load_kg,
    )


def plant_item(
    db: Session,
    r: SettingsResolver,
    plant: Plant,
    order_id: str,
    stop_position: int,
    species_cache: dict[uuid.UUID, Species],
) -> PlantItem:
    sp = None
    if plant.species_id:
        sp = species_cache.get(plant.species_id) or db.get(Species, plant.species_id)
        if sp is not None:
            species_cache[plant.species_id] = sp
    chain: list[tuple[str, uuid.UUID]] = [("plant", plant.id)]
    if sp is not None:
        chain.append(("species", sp.id))
        if sp.overrides_id:
            chain.append(("species", sp.overrides_id))
    g = geometry(plant)
    density = plant.crown_density if plant.crown_density is not None else 0.5
    compress = plant.compressibility if plant.compressibility is not None else 0.3
    base_overlap = float(r.get("packing.crown_overlap", *chain))
    # denser crowns overlap less, compressible ones more
    overlap = max(0.0, min(0.6, base_overlap * (1.3 - density) * (0.6 + compress)))
    return PlantItem(
        plant_id=str(plant.id),
        number=plant.number,
        order_id=order_id,
        stop_position=stop_position,
        label=f"#{plant.number} {plant.species_name or plant.label or t('packing.plant')}",
        weight=float(plant.weight_measured_kg or plant.weight_kg or 0),
        pot_shape=g.pot_shape,
        pot_d=g.pot_d,
        pot_l=g.pot_l,
        pot_w=g.pot_w,
        pot_h=g.pot_h,
        crown_shape=g.crown_shape,
        crown_w=g.crown_w,
        crown_h=g.crown_h,
        crown_start=g.crown_start,
        total_h=g.total_h,
        overlap=overlap,
        compress=compress,
        can_tilt=bool(plant.can_tilt),
        tilt_max_deg=float(r.get("packing.tilt_angle_deg", *chain)),
        sensitive=bool(plant.sensitive),
        must_secure=bool(plant.must_secure),
        tip_tendency=plant.tip_tendency if plant.tip_tendency is not None else DEFAULTS["tip_tendency"],
    )


def settings_for(r: SettingsResolver, direction: str, time_limit: float | None = None) -> PackSettings:
    return PackSettings(
        clearance=float(r.get("packing.clearance_cm")),
        heavy_kg=float(r.get("packing.heavy_kg")),
        cog_tolerance=float(r.get("packing.cog_tolerance")),
        tall_ratio=float(r.get("packing.tall_ratio")),
        time_limit_s=time_limit if time_limit is not None else float(r.get("packing.time_limit_s")),
        sort_rule=r.get("packing.sort_rule"),
        direction=direction,
    )


def result_payload(res: PackResult, spaces: list[Space]) -> dict[str, Any]:
    placements = []
    for p in sorted(res.placements, key=lambda q: q.seq):
        it = p.item
        lx, ly, h = it.bounding(p.orientation)
        placements.append(
            {
                "plant_id": it.plant_id,
                "order_id": it.order_id,
                "stop_position": it.stop_position,
                "number": it.number,
                "label": it.label,
                "sequence": p.seq,
                "space_id": p.space_id,
                "level": p.level,
                "orientation": p.orientation.name,
                "angle": p.orientation.angle,
                "x": round(p.x, 1),
                "y": round(p.y, 1),
                "z": round(p.z, 1),
                "dims": {
                    "pot_shape": it.pot_shape,
                    "pot_d": it.pot_d,
                    "pot_l": it.pot_l,
                    "pot_w": it.pot_w,
                    "pot_h": it.pot_h,
                    "crown_shape": it.crown_shape,
                    "crown_w": it.crown_w,
                    "crown_h": it.crown_h,
                    "crown_start": it.crown_start,
                    "total_h": it.total_h,
                    "box": [round(lx, 1), round(ly, 1), round(h, 1)],
                    "weight": it.weight,
                },
                "instruction": res.instructions.get(it.plant_id, {}).get("text", ""),
                "secure": res.instructions.get(it.plant_id, {}).get("secure", False),
            }
        )
    return {
        "placements": placements,
        "metrics": res.metrics,
        "violations": res.violations,
        "unplaced": res.unplaced,
        "spaces": [space_dict(s) for s in spaces],
        "iterations": res.iterations,
    }


def space_dict(s: Space) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "kind": s.kind,
        "length": s.length,
        "width": s.width,
        "height": s.height,
        "door_w": s.door_w,
        "door_h": s.door_h,
        "payload": s.payload,
        "obstacles": [o.__dict__ for o in s.obstacles],
        "shelves": [sh.__dict__ for sh in s.shelves],
    }


def pack_orders(
    db: Session,
    tenant_id: uuid.UUID,
    vehicle_ids: list[uuid.UUID],
    orders: list[PickupOrder],
    direction: str,
    time_limit: float | None = None,
) -> tuple[PackResult, list[Space]]:
    r = SettingsResolver(db, tenant_id)
    spaces = [space_from_vehicle(db, db.get(Vehicle, vid)) for vid in vehicle_ids if vid]
    items: list[PlantItem] = []
    cache: dict[uuid.UUID, Species] = {}
    for pos, order in enumerate(orders, start=1):
        source = order.return_of_id or order.id
        for plant in db.scalars(
            select(Plant).where(Plant.order_id == source, Plant.deleted_at.is_(None)).order_by(Plant.number)
        ):
            items.append(plant_item(db, r, plant, str(order.id), pos, cache))
    packer = Packer(spaces, settings_for(r, direction, time_limit))
    return packer.run(items), spaces


def pack_trip_check(db: Session, inp, trip) -> tuple[bool, str, dict[str, Any]]:
    """Hook for the tour planner: pack one solved trip (virtual vehicles of scenarios are skipped)."""
    unit = trip.unit
    if unit.vehicle.virtual:
        return True, "virtuelles Fahrzeug (Szenario)", {}
    vehicle_ids = [uuid.UUID(unit.vehicle.id)] + (
        [uuid.UUID(unit.trailer.id)] if unit.trailer and not unit.trailer.virtual else []
    )
    orders = [s.stop.order for s in trip.stops]
    r = SettingsResolver(db, inp.tenant_id)
    limit = min(float(r.get("packing.time_limit_s")), 2.0)
    res, spaces = pack_orders(
        db, inp.tenant_id, vehicle_ids, orders, orders[0].direction if orders else "pickup", limit
    )
    return res.ok, res.message, result_payload(res, spaces)


def pack_tour(db: Session, tour: Tour, time_limit: float | None = None) -> dict[str, Any]:
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == tour.id).order_by(TourStop.position)))
    orders = [db.get(PickupOrder, s.order_id) for s in stops]
    vehicle_ids = [vid for vid in (tour.vehicle_id, tour.trailer_id) if vid]
    if not vehicle_ids:
        tour.load_status = "unknown"
        tour.load_message = "kein reales Fahrzeug"
        return {}
    res, spaces = pack_orders(
        db, tour.tenant_id, vehicle_ids, orders, orders[0].direction if orders else "pickup", time_limit
    )
    payload = {"ok": res.ok, "message": res.message, **result_payload(res, spaces)}
    from app.packing.store import save_load_plan

    save_load_plan(db, tour, payload)
    return payload

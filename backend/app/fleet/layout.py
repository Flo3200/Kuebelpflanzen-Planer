"""Cargo-space layout of a vehicle: its own shelves (shelf editor) plus assigned modules.

Shelves are extra loading levels; fixtures are blocked boxes on the floor; the own weight of all
modules reduces the payload. Load planning and tour planning both read this layout.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fleet import VehicleModule, VehicleModuleLink
from app.models.masterdata import VehicleShelf


@dataclass
class ShelfSpec:
    id: str
    name: str
    x: float
    y: float
    length: float
    depth: float
    height: float
    clearance: float
    max_load: float
    blocks_floor: bool


@dataclass
class FixtureSpec:
    id: str
    name: str
    x: float
    y: float
    length: float
    depth: float
    height: float


@dataclass
class Layout:
    shelves: list[ShelfSpec] = field(default_factory=list)
    fixtures: list[FixtureSpec] = field(default_factory=list)
    module_weight: float = 0.0
    module_ids: list[str] = field(default_factory=list)

    def floor_blocked_cm2(self) -> float:
        return sum(s.length * s.depth for s in self.shelves if s.blocks_floor) + sum(
            f.length * f.depth for f in self.fixtures
        )

    def shelf_area_cm2(self) -> float:
        return sum(s.length * s.depth for s in self.shelves)


def modules_of(db: Session, vehicle_id: uuid.UUID) -> list[VehicleModule]:
    return list(
        db.scalars(
            select(VehicleModule)
            .join(VehicleModuleLink, VehicleModuleLink.module_id == VehicleModule.id)
            .where(VehicleModuleLink.vehicle_id == vehicle_id, VehicleModule.deleted_at.is_(None))
            .order_by(VehicleModule.name)
        )
    )


def vehicle_layout(db: Session, vehicle_id: uuid.UUID) -> Layout:
    out = Layout()
    for s in db.scalars(select(VehicleShelf).where(VehicleShelf.vehicle_id == vehicle_id)):
        out.shelves.append(
            ShelfSpec(
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
        )
    for m in modules_of(db, vehicle_id):
        out.module_ids.append(str(m.id))
        out.module_weight += float(m.weight_kg or 0)
        if m.kind == "shelf":
            out.shelves.append(
                ShelfSpec(
                    f"module:{m.id}",
                    m.name,
                    m.x_cm,
                    m.y_cm,
                    m.length_cm,
                    m.depth_cm,
                    m.height_cm,
                    m.clearance_cm if m.clearance_cm is not None else 60.0,
                    m.max_load_kg if m.max_load_kg is not None else 60.0,
                    bool(m.blocks_floor),
                )
            )
        else:
            out.fixtures.append(
                FixtureSpec(f"module:{m.id}", m.name, m.x_cm, m.y_cm, m.length_cm, m.depth_cm, m.height_cm)
            )
    return out


def module_vehicles(db: Session, tenant_id: uuid.UUID) -> dict[str, set[str]]:
    """module id -> ids of the vehicles it is assigned to."""
    out: dict[str, set[str]] = {}
    for link in db.scalars(select(VehicleModuleLink).where(VehicleModuleLink.tenant_id == tenant_id)):
        out.setdefault(str(link.module_id), set()).add(str(link.vehicle_id))
    return out

"""Staff, teams, vehicles (+ shelves), equipment, storage areas, availability, species."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.crud import ENTITIES, EntitySpec, apply_values, build_schemas, crud_router, row_dict
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.models.masterdata import (
    Availability,
    Equipment,
    Species,
    StaffMember,
    StorageArea,
    Team,
    Vehicle,
    VehicleShelf,
)
from app.planning.availability import day_windows
from app.settings.chains import CHAIN_BUILDERS
from app.settings.service import SettingsResolver

router = APIRouter()

STAFF = EntitySpec(
    "staff",
    StaffMember,
    "staff.read",
    "staff.write",
    search=("name", "email"),
    order_by=("name",),
    settings_scope="staff",
)
TEAM = EntitySpec("team", Team, "staff.read", "staff.write", order_by=("name",))
VEHICLE = EntitySpec(
    "vehicle",
    Vehicle,
    "fleet.read",
    "fleet.write",
    search=("name", "plate"),
    filters=("kind",),
    order_by=("name",),
    settings_scope="vehicle",
)
SHELF = EntitySpec(
    "shelf", VehicleShelf, "fleet.read", "fleet.write", filters=("vehicle_id",), order_by=("x_cm",)
)
EQUIPMENT = EntitySpec(
    "equipment",
    Equipment,
    "fleet.read",
    "fleet.write",
    filters=("vehicle_id", "kind"),
    order_by=("name",),
    settings_scope="equipment",
)
STORAGE = EntitySpec(
    "storage_area", StorageArea, "tenant.view", "tenant.profile", order_by=("name",), module="storage"
)
AVAIL = EntitySpec(
    "availability",
    Availability,
    "staff.read",
    "staff.write",
    filters=("resource_type", "resource_id", "kind"),
    order_by=("date_from",),
)


def _validate_team(db: Session, actor: Actor, row: Team, created: bool) -> None:
    ids = [str(x) for x in (row.member_ids or [])]
    if ids:
        found = set(
            str(i)
            for i in db.scalars(
                select(StaffMember.id).where(
                    StaffMember.id.in_([uuid.UUID(x) for x in ids]), StaffMember.tenant_id == actor.tenant_id
                )
            )
        )
        missing = [x for x in ids if x not in found]
        if missing:
            raise AppError("errors.validation")
    row.member_ids = ids


router.include_router(crud_router(STAFF, "/api/staff"))
router.include_router(crud_router(TEAM, "/api/teams", before_save=_validate_team))
router.include_router(crud_router(VEHICLE, "/api/vehicles"))
router.include_router(crud_router(SHELF, "/api/shelves"))
router.include_router(crud_router(EQUIPMENT, "/api/equipment"))
router.include_router(crud_router(STORAGE, "/api/storage-areas"))


def _availability_changed(db: Session, actor: Actor, row: Availability, created: bool) -> None:
    if row.kind != "available":
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, actor.require_tenant(), f"absence:{row.resource_type}:{row.date_from}")


router.include_router(crud_router(AVAIL, "/api/availability", after_save=_availability_changed))


@router.get("/api/availability-calendar", tags=["availability"])
def availability_calendar(
    actor: CurrentActor,
    db: DB,
    start: date,
    days: int = Query(14, ge=1, le=92),
) -> dict[str, Any]:
    """Resolved availability per resource and day (for the calendar view and the planner)."""
    actor.require("staff.read")
    tid = actor.require_tenant()
    resolver = SettingsResolver(db, tid)
    end = start + timedelta(days=days - 1)
    staff = list(
        db.scalars(
            select(StaffMember)
            .where(
                StaffMember.tenant_id == tid, StaffMember.deleted_at.is_(None), StaffMember.active.is_(True)
            )
            .order_by(StaffMember.name)
        )
    )
    vehicles = list(
        db.scalars(
            select(Vehicle)
            .where(Vehicle.tenant_id == tid, Vehicle.deleted_at.is_(None), Vehicle.active.is_(True))
            .order_by(Vehicle.name)
        )
    )
    resolver.prefetch("staff", [s.id for s in staff])
    resolver.prefetch("vehicle", [v.id for v in vehicles])
    sw = day_windows(db, resolver, "staff", [s.id for s in staff], start, end)
    vw = day_windows(db, resolver, "vehicle", [v.id for v in vehicles], start, end)

    def fmt(windows):
        return {
            d.isoformat(): {
                "available": w.available,
                "start": w.start.strftime("%H:%M") if w.start else None,
                "end": w.end.strftime("%H:%M") if w.end else None,
                "reason": w.reason,
            }
            for d, w in windows.items()
        }

    return {
        "start": start,
        "days": days,
        "staff": [{"id": s.id, "name": s.name, "days": fmt(sw[s.id])} for s in staff],
        "vehicles": [{"id": v.id, "name": v.name, "days": fmt(vw[v.id])} for v in vehicles],
    }


# ----------------------------------------------------------------------------- species

SPECIES = EntitySpec(
    "species",
    Species,
    "orders.read",
    "species.write",
    search=("name", "botanical_name"),
    order_by=("name",),
    settings_scope="species",
)
ENTITIES["species"] = SPECIES
SpeciesCreate, SpeciesUpdate, SpeciesRead = build_schemas(SPECIES)


def species_dict(s: Species, overridden_ids: set[uuid.UUID] | None = None) -> dict[str, Any]:
    d = row_dict(SPECIES, s)
    d["is_global"] = s.tenant_id is None
    d["is_override"] = s.overrides_id is not None
    d["has_override"] = bool(overridden_ids and s.id in overridden_ids)
    d["display_name"] = s.name + (f" ({s.botanical_name})" if s.botanical_name else "")
    return d


def visible_species(db: Session, tenant_id: uuid.UUID | None) -> list[Species]:
    """Effective catalog of a tenant: own species and overrides plus global species not overridden."""
    if tenant_id is None:
        return list(
            db.scalars(
                select(Species)
                .where(Species.tenant_id.is_(None), Species.deleted_at.is_(None))
                .order_by(Species.name)
            )
        )
    rows = list(
        db.scalars(
            select(Species)
            .where(
                or_(Species.tenant_id.is_(None), Species.tenant_id == tenant_id), Species.deleted_at.is_(None)
            )
            .order_by(Species.name)
        )
    )
    overridden = {r.overrides_id for r in rows if r.tenant_id == tenant_id and r.overrides_id}
    return [r for r in rows if r.id not in overridden]


@router.get("/api/species", tags=["species"])
def list_species(actor: CurrentActor, db: DB, q: str | None = None) -> list[dict[str, Any]]:
    """Internal knowledge base of plant species (admin only since the species moved to the plant)."""
    actor.require("platform.species")
    rows = visible_species(db, actor.tenant_id)
    if q:
        ql = q.lower()
        rows = [
            r
            for r in rows
            if ql in r.name.lower()
            or ql in (r.botanical_name or "").lower()
            or any(ql in str(a).lower() for a in (r.aliases or []))
        ]
    return [species_dict(r) for r in rows]


@router.get("/api/species/{species_id}", tags=["species"])
def get_species(species_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.species")
    row = db.get(Species, species_id)
    if row is None or (row.tenant_id is not None and row.tenant_id != actor.tenant_id):
        raise NotFound()
    return species_dict(row)


def _species_perm(actor: Actor) -> None:
    # tenants no longer maintain species: the AI stores species and properties on the plant
    actor.require("platform.species")


@router.post("/api/species", status_code=201, tags=["species"])
def create_species(data: SpeciesCreate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    _species_perm(actor)
    row = Species(tenant_id=actor.tenant_id)
    apply_values(SPECIES, row, data.model_dump())  # type: ignore[attr-defined]
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="species",
        entity_id=row.id,
        action="create",
        new=row_dict(SPECIES, row),
    )
    return species_dict(row)


@router.patch("/api/species/{species_id}", tags=["species"])
def update_species(species_id: uuid.UUID, data: SpeciesUpdate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    """A tenant changing a global species gets its own override row; the global row stays as is."""
    _species_perm(actor)
    row = db.get(Species, species_id)
    if row is None or (row.tenant_id is not None and row.tenant_id != actor.tenant_id):
        raise NotFound()
    values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    if row.tenant_id is None and actor.tenant_id is not None:
        base = row
        row = Species(tenant_id=actor.tenant_id, overrides_id=base.id)
        apply_values(SPECIES, row, {c.name: getattr(base, c.name) for c in SPECIES.writable()})
        db.add(row)
        db.flush()
        audit.record(
            db,
            actor,
            tenant_id=actor.tenant_id,
            entity="species",
            entity_id=row.id,
            action="override",
            new={"overrides": str(base.id)},
        )
    changes = apply_values(SPECIES, row, values)
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=row.tenant_id,
            entity="species",
            entity_id=row.id,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    db.flush()
    return species_dict(row)


@router.delete("/api/species/{species_id}", tags=["species"])
def delete_species(species_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Deletes an own species; for an override this resets to the global species."""
    _species_perm(actor)
    from app.agents.confirm import confirm_if_agent

    confirm_if_agent(db, actor, "delete:species", {"id": str(species_id)})
    row = db.get(Species, species_id)
    if row is None or (row.tenant_id is not None and row.tenant_id != actor.tenant_id):
        raise NotFound()
    if row.tenant_id is None and actor.tenant_id is not None:
        raise NotFound()
    audit.record(
        db,
        actor,
        tenant_id=row.tenant_id,
        entity="species",
        entity_id=row.id,
        action="reset" if row.overrides_id else "delete",
        old=row_dict(SPECIES, row),
    )
    if row.overrides_id:
        from app.models.orders import Plant

        for plant in db.scalars(select(Plant).where(Plant.species_id == row.id)):
            plant.species_id = row.overrides_id
        db.delete(row)
    else:
        from datetime import UTC, datetime

        row.deleted_at = datetime.now(UTC)
    return {"ok": True}


def species_chain(db: Session, species_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    row = db.get(Species, species_id)
    chain = [("species", species_id)]
    if row is not None and row.overrides_id:
        chain.append(("species", row.overrides_id))
    return chain


CHAIN_BUILDERS["species"] = species_chain


class ShelfBulk(BaseModel):
    shelves: list[dict[str, Any]]


@router.put("/api/vehicles/{vehicle_id}/shelves", tags=["vehicle"])
def replace_shelves(
    vehicle_id: uuid.UUID, data: ShelfBulk, actor: CurrentActor, db: DB
) -> list[dict[str, Any]]:
    """Replace all shelves of a vehicle (used by the shelf editor)."""
    actor.require("fleet.write")
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.tenant_id != actor.tenant_id:
        raise NotFound()
    old = [
        row_dict(SHELF, s)
        for s in db.scalars(select(VehicleShelf).where(VehicleShelf.vehicle_id == vehicle_id))
    ]
    for s in db.scalars(select(VehicleShelf).where(VehicleShelf.vehicle_id == vehicle_id)):
        db.delete(s)
    db.flush()
    out = []
    for item in data.shelves:
        shelf = VehicleShelf(tenant_id=actor.tenant_id, vehicle_id=vehicle_id)
        apply_values(SHELF, shelf, {k: v for k, v in item.items() if k != "id"})
        shelf.vehicle_id = vehicle_id
        db.add(shelf)
        out.append(shelf)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="vehicle",
        entity_id=vehicle_id,
        action="shelves",
        old=old,
        new=[row_dict(SHELF, s) for s in out],
    )
    return [row_dict(SHELF, s) for s in out]

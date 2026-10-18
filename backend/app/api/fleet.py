"""Modular vehicles (package C): modules, assignment to vehicles, trailer combinations, vehicle drafts
from cargo-space photos or a chat."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.crud import EntitySpec, crud_router, row_dict
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.fleet import drafts as vd
from app.fleet.layout import module_vehicles, modules_of
from app.models.fleet import VehicleDraft, VehicleModule, VehicleModuleLink
from app.models.masterdata import Vehicle

router = APIRouter()

MODULE = EntitySpec(
    "vehicle_module",
    VehicleModule,
    "fleet.read",
    "fleet.write",
    search=("name",),
    filters=("kind",),
    order_by=("name",),
)


def _validate_module(db: Session, actor: Actor, row: VehicleModule, created: bool) -> None:
    for k in ("length_cm", "depth_cm", "height_cm"):
        if (getattr(row, k) or 0) <= 0:
            raise AppError("errors.validation")
    if row.kind == "shelf" and row.clearance_cm is None:
        row.clearance_cm = 60.0
    if row.kind == "shelf" and row.max_load_kg is None:
        row.max_load_kg = 60.0


def _module_changed(db: Session, actor: Actor, row: VehicleModule, created: bool) -> None:
    if not created:
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, actor.require_tenant(), f"module:{row.name}")


router.include_router(
    crud_router(MODULE, "/api/vehicle-modules", before_save=_validate_module, after_save=_module_changed)
)


@router.get("/api/module-assignments", tags=["vehicle_module"])
def assignments(actor: CurrentActor, db: DB) -> dict[str, list[str]]:
    """Module id -> vehicles it is assigned to."""
    actor.require("fleet.read")
    return {k: sorted(v) for k, v in module_vehicles(db, actor.require_tenant()).items()}


class ModulesIn(BaseModel):
    module_ids: list[uuid.UUID]


def _vehicle(db: Session, actor: Actor, vehicle_id: uuid.UUID) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if v is None or v.tenant_id != actor.tenant_id or v.deleted_at is not None:
        raise NotFound()
    return v


@router.get("/api/vehicles/{vehicle_id}/modules", tags=["vehicle"])
def vehicle_modules(vehicle_id: uuid.UUID, actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("fleet.read")
    _vehicle(db, actor, vehicle_id)
    return [row_dict(MODULE, m) for m in modules_of(db, vehicle_id)]


@router.put("/api/vehicles/{vehicle_id}/modules", tags=["vehicle"])
def set_vehicle_modules(
    vehicle_id: uuid.UUID, data: ModulesIn, actor: CurrentActor, db: DB
) -> list[dict[str, Any]]:
    """Assign modules to a vehicle (replaces the assignment). A module can sit in several vehicles."""
    actor.require("fleet.write")
    v = _vehicle(db, actor, vehicle_id)
    wanted = {m for m in data.module_ids}
    for mid in wanted:
        m = db.get(VehicleModule, mid)
        if m is None or m.tenant_id != v.tenant_id or m.deleted_at is not None:
            raise AppError("errors.validation")
    links = list(db.scalars(select(VehicleModuleLink).where(VehicleModuleLink.vehicle_id == v.id)))
    old = sorted(str(link.module_id) for link in links)
    for link in links:
        if link.module_id not in wanted:
            db.delete(link)
    have = {link.module_id for link in links}
    for mid in wanted - have:
        db.add(VehicleModuleLink(tenant_id=v.tenant_id, vehicle_id=v.id, module_id=mid))
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=v.tenant_id,
        entity="vehicle",
        entity_id=v.id,
        action="modules",
        old=old,
        new=sorted(str(m) for m in wanted),
    )
    from app.api.planning import mark_needs_replan

    mark_needs_replan(db, v.tenant_id, f"vehicle:{v.name}")
    return [row_dict(MODULE, m) for m in modules_of(db, v.id)]


@router.get("/api/vehicle-combinations", tags=["vehicle"])
def combinations(actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Tow vehicle + trailer combinations (the tow vehicle's default trailer)."""
    actor.require("fleet.read")
    tid = actor.require_tenant()
    vehicles = list(
        db.scalars(
            select(Vehicle)
            .where(Vehicle.tenant_id == tid, Vehicle.deleted_at.is_(None))
            .order_by(Vehicle.name)
        )
    )
    trailers = [v for v in vehicles if v.kind == "trailer"]
    names = {v.id: v.name for v in vehicles}
    return {
        "trailers": [{"id": t.id, "name": t.name, "payload_kg": t.payload_kg} for t in trailers],
        "tow_vehicles": [
            {
                "id": v.id,
                "name": v.name,
                "can_tow": v.can_tow,
                "required_licence": v.required_licence,
                "trailer_id": v.default_trailer_id,
                "trailer": names.get(v.default_trailer_id) if v.default_trailer_id else None,
            }
            for v in vehicles
            if v.kind != "trailer"
        ],
    }


class TrailerIn(BaseModel):
    trailer_id: uuid.UUID | None


@router.put("/api/vehicles/{vehicle_id}/trailer", tags=["vehicle"])
def set_trailer(vehicle_id: uuid.UUID, data: TrailerIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Combine a tow vehicle with a trailer (or separate them). A trailer may belong to several
    tow vehicles; the planner uses it with one of them per day."""
    actor.require("fleet.write")
    v = _vehicle(db, actor, vehicle_id)
    if v.kind == "trailer":
        raise AppError("errors.combination_invalid")
    if data.trailer_id is not None:
        t = _vehicle(db, actor, data.trailer_id)
        if t.kind != "trailer":
            raise AppError("errors.combination_invalid")
        if not v.can_tow:
            v.can_tow = True
    old = str(v.default_trailer_id) if v.default_trailer_id else None
    v.default_trailer_id = data.trailer_id
    audit.record(
        db,
        actor,
        tenant_id=v.tenant_id,
        entity="vehicle",
        entity_id=v.id,
        action="update",
        old={"default_trailer_id": old},
        new={"default_trailer_id": str(data.trailer_id) if data.trailer_id else None},
        undoable=True,
    )
    from app.api.planning import mark_needs_replan

    mark_needs_replan(db, v.tenant_id, f"vehicle:{v.name}")
    return {"ok": True, "trailer_id": v.default_trailer_id}


# ----------------------------------------------------------------------------- vehicle drafts


class ChatIn(BaseModel):
    message: str
    draft_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None  # change an existing vehicle


class CorrectIn(BaseModel):
    data: dict[str, Any]


def _perm(actor: Actor) -> None:
    actor.require("fleet.write")
    actor.require("ai.use")


@router.get("/api/vehicle-drafts", tags=["vehicle_draft"])
def list_drafts(actor: CurrentActor, db: DB, status: str = "open") -> list[dict[str, Any]]:
    actor.require("fleet.read")
    q = select(VehicleDraft).where(VehicleDraft.tenant_id == actor.require_tenant())
    if status != "all":
        q = q.where(VehicleDraft.status == status)
    return [vd.draft_dict(d) for d in db.scalars(q.order_by(VehicleDraft.created_at.desc()).limit(100))]


@router.get("/api/vehicle-drafts/{draft_id}", tags=["vehicle_draft"])
def get_draft(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("fleet.read")
    d = db.get(VehicleDraft, draft_id)
    if d is None or d.tenant_id != actor.tenant_id:
        raise NotFound()
    return vd.draft_dict(d)


@router.post("/api/vehicle-drafts/chat", tags=["vehicle_draft"])
def chat(data: ChatIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Describe a vehicle in your own words (or what should change); the AI answers with a draft and
    asks for missing values. Continue with draft_id."""
    _perm(actor)
    if not data.message.strip():
        raise AppError("errors.validation")
    return vd.draft_dict(vd.chat(db, actor, data.message.strip(), data.draft_id, data.vehicle_id))


@router.post("/api/vehicle-drafts/photo", status_code=201, tags=["vehicle_draft"])
async def photo(
    actor: CurrentActor,
    db: DB,
    files: list[UploadFile] = File(...),
    note: str | None = Form(None, description="optional: Angaben aus dem Fahrzeugschein, Nutzlast …"),
    vehicle_id: uuid.UUID | None = Form(None),
) -> dict[str, Any]:
    """Photos of the cargo space with an A4 sheet or a folding rule as scale -> vehicle draft."""
    _perm(actor)
    raw = [(await f.read(), f.filename or "laderaum.jpg") for f in files]
    return vd.draft_dict(vd.from_photos(db, actor, raw, note, vehicle_id))


@router.patch("/api/vehicle-drafts/{draft_id}", tags=["vehicle_draft"])
def correct(draft_id: uuid.UUID, data: CorrectIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    return vd.draft_dict(vd.correct(db, actor, vd.get_open(db, actor, draft_id), data.data))


@router.post("/api/vehicle-drafts/{draft_id}/confirm", tags=["vehicle_draft"])
def confirm(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    from app.agents.confirm import confirm_if_agent

    confirm_if_agent(db, actor, "vehicle_draft:confirm", {"id": str(draft_id)})
    vehicle = vd.confirm(db, actor, vd.get_open(db, actor, draft_id))
    return {
        "vehicle_id": vehicle.id,
        "name": vehicle.name,
        "draft": vd.draft_dict(db.get(VehicleDraft, draft_id)),
    }


@router.post("/api/vehicle-drafts/{draft_id}/discard", tags=["vehicle_draft"])
def discard(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _perm(actor)
    d = vd.get_open(db, actor, draft_id)
    d.status = "discarded"
    return {"ok": True}

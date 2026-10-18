"""Customers, addresses, pickup orders, plants and access paths."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.crud import (
    ENTITIES,
    EntitySpec,
    apply_values,
    build_schemas,
    check_foreign_keys,
    crud_router,
    row_dict,
)
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.core.numbering import next_number
from app.models.masterdata import Species
from app.models.orders import (
    AccessPath,
    Address,
    Customer,
    PathSegment,
    Photo,
    PickupOrder,
    Plant,
)
from app.settings.chains import CHAIN_BUILDERS
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import complete_plant

router = APIRouter()

CUSTOMER = EntitySpec(
    "customer",
    Customer,
    "customers.read",
    "customers.write",
    search=("name", "email", "phone", "company"),
    order_by=("name",),
    settings_scope="customer",
)
ADDRESS = EntitySpec(
    "address",
    Address,
    "customers.read",
    "customers.write",
    filters=("customer_id",),
    order_by=("created_at",),
)
ORDER = EntitySpec("order", PickupOrder, "orders.read", "orders.write", order_by=("-created_at",))
PLANT = EntitySpec(
    "plant",
    Plant,
    "orders.read",
    "orders.write",
    filters=("order_id",),
    order_by=("number",),
    settings_scope="plant",
)
SEGMENT = EntitySpec("segment", PathSegment, "orders.read", "orders.write", order_by=("position",))
PATH = EntitySpec("access_path", AccessPath, "orders.read", "orders.write")
for spec in (ORDER, PLANT, SEGMENT, PATH):
    ENTITIES[spec.name] = spec
OrderCreate, OrderUpdate, OrderRead = build_schemas(ORDER)
PlantCreate, PlantUpdate, PlantRead = build_schemas(PLANT)


def _geocode_hook(db: Session, actor: Actor, row: Address, created: bool) -> None:
    if row.lat is not None and row.lon is not None:
        if row.geocode_source is None:
            row.geocode_source = "manual"
        return
    from app.routing.geocode import geocode

    result = geocode(f"{row.street}, {row.postal_code} {row.city}, {row.country}")
    if result is not None:
        row.lat, row.lon, row.geocode_source = result[0], result[1], result[2]


router.include_router(crud_router(CUSTOMER, "/api/customers"))
router.include_router(crud_router(ADDRESS, "/api/addresses", before_save=_geocode_hook))


# ----------------------------------------------------------------------------- helpers


def path_summary(segments: list[PathSegment], confirmed_length: float | None = None) -> dict[str, Any]:
    length = sum(s.length_m or 0 for s in segments)
    steps = sum(s.steps or 0 for s in segments)
    height = sum(abs(s.height_diff_m or 0) for s in segments)
    if height == 0 and steps:
        height = steps * 0.17
    widths = [s.min_width_cm for s in segments if s.min_width_cm]
    return {
        "length_m": round(confirmed_length if confirmed_length else length, 1),
        "length_from_segments_m": round(length, 1),
        "steps": steps,
        "height_m": round(height, 2),
        "min_width_cm": min(widths) if widths else None,
        "doors": sum(s.doors or 0 for s in segments),
        "max_slope_pct": max((s.slope_pct or 0 for s in segments), default=0),
        "has_stairs": any((s.steps or 0) > 0 or s.kind == "stairs" for s in segments),
        "has_elevator": any(s.elevator for s in segments),
        "surfaces": sorted({s.surface for s in segments if s.surface}),
        "segments": len(segments),
    }


def get_order(db: Session, actor: Actor, order_id: uuid.UUID) -> PickupOrder:
    order = db.get(PickupOrder, order_id)
    if order is None or order.deleted_at is not None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    return order


def order_plants(db: Session, order: PickupOrder) -> list[Plant]:
    """Plants of an order; a return order uses the plants of its pickup."""
    source_id = order.return_of_id or order.id
    return list(
        db.scalars(
            select(Plant)
            .where(Plant.order_id == source_id, Plant.deleted_at.is_(None))
            .order_by(Plant.number)
        )
    )


def order_paths(db: Session, order: PickupOrder) -> list[tuple[AccessPath, list[PathSegment]]]:
    source_id = order.return_of_id or order.id
    out = []
    for p in db.scalars(
        select(AccessPath).where(AccessPath.order_id == source_id).order_by(AccessPath.created_at)
    ):
        segs = list(
            db.scalars(select(PathSegment).where(PathSegment.path_id == p.id).order_by(PathSegment.position))
        )
        out.append((p, segs))
    return out


def plant_dict(p: Plant, species_name: str | None = None) -> dict[str, Any]:
    d = row_dict(PLANT, p)
    d["species_name"] = species_name
    d["display_name"] = f"#{p.number} {p.label or species_name or ''}".strip()
    return d


def order_list_row(
    order: PickupOrder, customer: Customer | None, address: Address | None, n_plants: int
) -> dict[str, Any]:
    d = row_dict(ORDER, order)
    d["customer_name"] = customer.name if customer else None
    d["city"] = address.city if address else None
    d["postal_code"] = address.postal_code if address else None
    d["lat"] = address.lat if address else None
    d["lon"] = address.lon if address else None
    d["n_plants"] = n_plants
    d["display_name"] = f"{order.number} · {customer.name if customer else ''}"
    est = order.estimate or {}
    d["duration_min"] = est.get("duration_min")
    d["labour_min"] = est.get("labour_min")
    d["team_size"] = est.get("team_size")
    return d


# ----------------------------------------------------------------------------- customers


@router.get("/api/customers/{customer_id}/full", tags=["customer"])
def customer_full(customer_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("customers.read")
    c = db.get(Customer, customer_id)
    if c is None or c.deleted_at is not None or c.tenant_id != actor.tenant_id:
        raise NotFound()
    addresses = list(
        db.scalars(select(Address).where(Address.customer_id == c.id, Address.deleted_at.is_(None)))
    )
    orders = list(
        db.scalars(
            select(PickupOrder)
            .where(PickupOrder.customer_id == c.id, PickupOrder.deleted_at.is_(None))
            .order_by(PickupOrder.created_at.desc())
        )
    )
    addr_by_id = {a.id: a for a in addresses}
    counts = (
        dict(
            db.execute(
                select(Plant.order_id, func.count())
                .where(Plant.order_id.in_([o.id for o in orders]), Plant.deleted_at.is_(None))
                .group_by(Plant.order_id)
            ).all()
        )
        if orders
        else {}
    )
    return {
        "customer": row_dict(CUSTOMER, c),
        "addresses": [row_dict(ADDRESS, a) for a in addresses],
        "orders": [order_list_row(o, c, addr_by_id.get(o.address_id), counts.get(o.id, 0)) for o in orders],
    }


# ----------------------------------------------------------------------------- orders


@router.get("/api/orders", tags=["order"])
def list_orders(
    actor: CurrentActor,
    db: DB,
    status: list[str] = Query(default=[]),
    season: int | None = None,
    direction: str | None = None,
    q: str | None = None,
    limit: int = Query(1000, le=5000),
) -> list[dict[str, Any]]:
    actor.require("orders.read")
    tid = actor.require_tenant()
    stmt = (
        select(PickupOrder, Customer, Address)
        .join(Customer, Customer.id == PickupOrder.customer_id)
        .join(Address, Address.id == PickupOrder.address_id)
        .where(PickupOrder.tenant_id == tid, PickupOrder.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(PickupOrder.status.in_(status))
    if season:
        stmt = stmt.where(PickupOrder.season == season)
    if direction:
        stmt = stmt.where(PickupOrder.direction == direction)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                PickupOrder.number.ilike(like),
                Customer.name.ilike(like),
                Address.city.ilike(like),
                Address.street.ilike(like),
            )
        )
    rows = db.execute(stmt.order_by(PickupOrder.created_at.desc()).limit(limit)).all()
    ids = [o.return_of_id or o.id for o, _, _ in rows]
    counts = (
        dict(
            db.execute(
                select(Plant.order_id, func.count())
                .where(Plant.order_id.in_(ids), Plant.deleted_at.is_(None))
                .group_by(Plant.order_id)
            ).all()
        )
        if ids
        else {}
    )
    return [order_list_row(o, c, a, counts.get(o.return_of_id or o.id, 0)) for o, c, a in rows]


def new_order(db: Session, actor: Actor, values: dict[str, Any]) -> PickupOrder:
    tid = actor.require_tenant()
    check_foreign_keys(db, ORDER, values)
    address = db.get(Address, values["address_id"])
    if address is None or address.customer_id != values["customer_id"]:
        raise AppError("errors.validation")
    season = values.get("season") or _current_season(db, tid)
    order = PickupOrder(tenant_id=tid, season=season, status="draft")
    apply_values(ORDER, order, {**values, "season": season})
    prefix = "R" if order.direction == "return" else "A"
    order.number = f"{prefix}-{season}-{next_number(db, tid, f'order-{season}'):04d}"
    db.add(order)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="order",
        entity_id=order.id,
        action="create",
        new=row_dict(ORDER, order),
    )
    return order


def _current_season(db: Session, tenant_id: uuid.UUID) -> int:
    start_month = SettingsResolver(db, tenant_id).get("general.season_start_month")
    today = date.today()
    return today.year if today.month >= start_month else today.year - 1


@router.post("/api/orders", status_code=201, tags=["order"])
def create_order(data: OrderCreate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    actor.require("orders.write")
    order = new_order(db, actor, data.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    return order_detail(db, actor, order)


def order_detail(db: Session, actor: Actor, order: PickupOrder) -> dict[str, Any]:
    customer = db.get(Customer, order.customer_id)
    address = db.get(Address, order.address_id)
    plants = order_plants(db, order)
    species_ids = {p.species_id for p in plants if p.species_id}
    names = (
        {s.id: s.name for s in db.scalars(select(Species).where(Species.id.in_(species_ids)))}
        if species_ids
        else {}
    )
    paths = order_paths(db, order)
    photos = list(
        db.scalars(
            select(Photo)
            .where(Photo.order_id == (order.return_of_id or order.id))
            .order_by(Photo.kind, Photo.position)
        )
    )
    from app.api.files import photo_dict

    return {
        "order": row_dict(ORDER, order) | {"estimate": order.estimate},
        "customer": row_dict(CUSTOMER, customer) if customer else None,
        "address": row_dict(ADDRESS, address) if address else None,
        "plants": [plant_dict(p, names.get(p.species_id)) for p in plants],
        "paths": [
            {
                **row_dict(PATH, p),
                "segments": [row_dict(SEGMENT, s) for s in segs],
                "summary": path_summary(segs, p.length_confirmed_m),
            }
            for p, segs in paths
        ],
        "photos": [photo_dict(ph) for ph in photos],
    }


@router.get("/api/orders/{order_id}", tags=["order"])
def get_order_detail(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.read")
    order = get_order(db, actor, order_id)
    if order.status not in ("cancelled", "returned"):
        # recompute live so changed formulas and settings show immediately
        _after_order_change(db, actor, order, {})
    return order_detail(db, actor, order)


@router.patch("/api/orders/{order_id}", tags=["order"])
def update_order(order_id: uuid.UUID, data: OrderUpdate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    actor.require("orders.write")
    order = get_order(db, actor, order_id)
    values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    check_foreign_keys(db, ORDER, values)
    old_status = order.status
    changes = apply_values(ORDER, order, values)
    if order.status == "cancelled" and old_status != "cancelled":
        order.cancelled_at = datetime.now(UTC)
        from app.api.planning import cancel_stops_of_order, mark_needs_replan

        cancel_stops_of_order(db, order)
        mark_needs_replan(db, order.tenant_id, f"cancelled:{order.number}", order.direction)
    elif order.status == "confirmed" and old_status == "draft":
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, order.tenant_id, f"new_order:{order.number}", order.direction)
    elif {"earliest_date", "latest_date", "fixed_date", "time_windows"} & set(changes) and order.status in (
        "confirmed",
        "planned",
    ):
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, order.tenant_id, f"changed:{order.number}", order.direction)
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=order.tenant_id,
            entity="order",
            entity_id=order.id,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    db.flush()
    _after_order_change(db, actor, order, changes)
    return order_detail(db, actor, order)


def _after_order_change(db: Session, actor: Actor, order: PickupOrder, changes: dict[str, Any]) -> None:
    """Hook for estimates (phase 3) and replanning hints (phase 4)."""
    try:
        from app.timemodel.service import refresh_order_estimate
    except ModuleNotFoundError:
        return
    refresh_order_estimate(db, order)


@router.delete("/api/orders/{order_id}", tags=["order"])
def delete_order(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    from app.agents.confirm import confirm_if_agent

    confirm_if_agent(db, actor, "delete:order", {"id": str(order_id)})
    order = get_order(db, actor, order_id)
    order.deleted_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        tenant_id=order.tenant_id,
        entity="order",
        entity_id=order.id,
        action="delete",
        old=row_dict(ORDER, order),
    )
    return {"ok": True}


def make_return(
    db: Session, actor: Actor, pickup: PickupOrder, earliest: date | None = None, latest: date | None = None
) -> tuple[PickupOrder, bool]:
    """Spring return of a pickup: reuses plants and paths, keeps the customer's time windows
    (without fixed dates). Returns (order, created)."""
    existing = db.scalar(
        select(PickupOrder).where(PickupOrder.return_of_id == pickup.id, PickupOrder.deleted_at.is_(None))
    )
    if existing is not None:
        return existing, False
    ret = new_order(
        db,
        actor,
        {
            "customer_id": pickup.customer_id,
            "address_id": pickup.address_id,
            "season": pickup.season,
            "direction": "return",
            "notes": pickup.notes,
        },
    )
    ret.return_of_id = pickup.id
    ret.time_windows = [w for w in (pickup.time_windows or []) if not w.get("date")]
    ret.earliest_date = earliest
    ret.latest_date = latest
    ret.status = "confirmed"
    db.flush()
    _after_order_change(db, actor, ret, {})
    return ret, True


@router.post("/api/orders/{order_id}/return", status_code=201, tags=["order"])
def create_return(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Spring return: a new order in direction 'return' that reuses plants and paths of the pickup."""
    actor.require("orders.write")
    pickup = get_order(db, actor, order_id)
    if pickup.direction != "pickup":
        raise AppError("errors.validation")
    ret, _created = make_return(db, actor, pickup)
    return order_detail(db, actor, ret)


class ReturnsIn(BaseModel):
    earliest_date: date
    latest_date: date | None = None
    statuses: list[str] = ["picked_up", "stored"]
    season: int | None = None
    order_ids: list[uuid.UUID] | None = None


@router.post("/api/orders/returns", tags=["order"])
def create_returns(data: ReturnsIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Spring: returns for all stored pickups (or the given ones) at once, in one date range."""
    actor.require("orders.write")
    tid = actor.require_tenant()
    days = int(SettingsResolver(db, tid).get("returns.default_window_days"))
    latest = data.latest_date or data.earliest_date + timedelta(days=days)
    if latest < data.earliest_date:
        raise AppError("errors.validation")
    statuses = [x for x in data.statuses if x in ("confirmed", "planned", "picked_up", "stored")] or [
        "picked_up",
        "stored",
    ]
    q = select(PickupOrder).where(
        PickupOrder.tenant_id == tid,
        PickupOrder.deleted_at.is_(None),
        PickupOrder.direction == "pickup",
        PickupOrder.status.in_(statuses),
    )
    if data.season:
        q = q.where(PickupOrder.season == data.season)
    if data.order_ids:
        q = q.where(PickupOrder.id.in_(data.order_ids))
    created, existing = [], 0
    for pickup in db.scalars(q.order_by(PickupOrder.number)):
        ret, new = make_return(db, actor, pickup, data.earliest_date, latest)
        if new:
            created.append(ret.number)
        else:
            existing += 1
    if created:
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, tid, f"returns:{len(created)}", "return")
    return {
        "created": len(created),
        "numbers": created,
        "existing": existing,
        "earliest_date": data.earliest_date,
        "latest_date": latest,
    }


# ----------------------------------------------------------------------------- plants


def _species_for(db: Session, species_id: uuid.UUID | None) -> Species | None:
    return db.get(Species, species_id) if species_id else None


@router.post("/api/orders/{order_id}/plants", status_code=201, tags=["plant"])
def add_plant(order_id: uuid.UUID, data: PlantCreate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    actor.require("orders.write")
    order = get_order(db, actor, order_id)
    values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    plant = create_plant(db, actor, order, values)
    _after_order_change(db, actor, order, {})
    species = _species_for(db, plant.species_id)
    return plant_dict(plant, species.name if species else None)


def create_plant(
    db: Session,
    actor: Actor,
    order: PickupOrder,
    values: dict[str, Any],
    *,
    confidence: dict[str, float] | None = None,
    path_id: uuid.UUID | None = None,
) -> Plant:
    check_foreign_keys(db, PLANT, values)
    plant = Plant(
        tenant_id=order.tenant_id,
        order_id=order.id,
        estimated_fields=[],
        field_confidence=confidence or {},
        required_equipment=[],
        incompatible_with=[],
    )
    apply_values(PLANT, plant, values)
    plant.number = next_number(db, order.tenant_id, "plant")
    if path_id is None:
        first = db.scalar(
            select(AccessPath.id)
            .where(AccessPath.order_id == order.id)
            .order_by(AccessPath.created_at)
            .limit(1)
        )
        path_id = first
    plant.access_path_id = path_id
    db.add(plant)
    db.flush()
    complete_plant(db, plant, SettingsResolver(db, order.tenant_id), _species_for(db, plant.species_id))
    audit.record(
        db,
        actor,
        tenant_id=order.tenant_id,
        entity="plant",
        entity_id=plant.id,
        action="create",
        new=row_dict(PLANT, plant),
    )
    return plant


@router.get("/api/plants", tags=["plant"])
def list_plants(
    actor: CurrentActor,
    db: DB,
    order_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(2000, le=10000),
) -> list[dict[str, Any]]:
    actor.require("orders.read")
    stmt = (
        select(Plant, Species.name)
        .outerjoin(Species, Species.id == Plant.species_id)
        .where(Plant.tenant_id == actor.require_tenant(), Plant.deleted_at.is_(None))
    )
    if order_id:
        stmt = stmt.where(Plant.order_id == order_id)
    if status:
        stmt = stmt.where(Plant.status == status)
    if q:
        stmt = stmt.where(or_(Plant.label.ilike(f"%{q}%"), Species.name.ilike(f"%{q}%")))
    return [plant_dict(p, n) for p, n in db.execute(stmt.order_by(Plant.number).limit(limit)).all()]


def _get_plant(db: Session, actor: Actor, plant_id: uuid.UUID) -> Plant:
    plant = db.get(Plant, plant_id)
    if plant is None or plant.deleted_at is not None or plant.tenant_id != actor.tenant_id:
        raise NotFound()
    return plant


@router.get("/api/plants/{plant_id}", tags=["plant"])
def get_plant(plant_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.read")
    plant = _get_plant(db, actor, plant_id)
    species = _species_for(db, plant.species_id)
    return plant_dict(plant, species.name if species else None)


@router.patch("/api/plants/{plant_id}", tags=["plant"])
def update_plant(plant_id: uuid.UUID, data: PlantUpdate, actor: CurrentActor, db: DB) -> dict[str, Any]:  # type: ignore[valid-type]
    actor.require("orders.write")
    plant = _get_plant(db, actor, plant_id)
    values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    check_foreign_keys(db, PLANT, values)
    changes = apply_values(PLANT, plant, values)
    # values set by a person are no longer estimates
    plant.estimated_fields = [f for f in (plant.estimated_fields or []) if f not in values]
    if "species_id" in changes:
        # re-derive species-dependent defaults that were only estimates
        for f in (
            "crown_shape",
            "crown_density",
            "compressibility",
            "can_tilt",
            "sensitive",
            "frost_sensitive",
        ):
            if f in (plant.estimated_fields or []):
                setattr(plant, f, None)
    if changes and "weight_kg" not in values and "weight_kg" in (plant.estimated_fields or []):
        plant.weight_kg = None
    complete_plant(db, plant, SettingsResolver(db, plant.tenant_id))
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=plant.tenant_id,
            entity="plant",
            entity_id=plant.id,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    db.flush()
    order = db.get(PickupOrder, plant.order_id)
    if order:
        _after_order_change(db, actor, order, changes)
    species = _species_for(db, plant.species_id)
    return plant_dict(plant, species.name if species else None)


@router.delete("/api/plants/{plant_id}", tags=["plant"])
def delete_plant(plant_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    from app.agents.confirm import confirm_if_agent

    confirm_if_agent(db, actor, "delete:plant", {"id": str(plant_id)})
    plant = _get_plant(db, actor, plant_id)
    plant.deleted_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        tenant_id=plant.tenant_id,
        entity="plant",
        entity_id=plant.id,
        action="delete",
        old=row_dict(PLANT, plant),
    )
    order = db.get(PickupOrder, plant.order_id)
    if order:
        db.flush()
        _after_order_change(db, actor, order, {})
    return {"ok": True}


def plant_chain(db: Session, plant_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    plant = db.get(Plant, plant_id)
    chain: list[tuple[str, uuid.UUID]] = [("plant", plant_id)]
    if plant is not None and plant.species_id:
        from app.api.masterdata import species_chain

        chain += species_chain(db, plant.species_id)
    return chain


CHAIN_BUILDERS["plant"] = plant_chain


# ----------------------------------------------------------------------------- access paths


class PathIn(BaseModel):
    name: str = "Weg"
    length_confirmed_m: float | None = None
    notes: str | None = None


class SegmentsIn(BaseModel):
    segments: list[dict[str, Any]]


def create_path(
    db: Session,
    actor: Actor,
    order: PickupOrder,
    data: dict[str, Any],
    segments: list[dict[str, Any]],
    confidence: dict[str, Any] | None = None,
) -> AccessPath:
    path = AccessPath(tenant_id=order.tenant_id, order_id=order.id, confidence=confidence or {})
    apply_values(PATH, path, data)
    db.add(path)
    db.flush()
    _replace_segments(db, path, segments)
    # plants without a path get this one
    for plant in db.scalars(select(Plant).where(Plant.order_id == order.id, Plant.access_path_id.is_(None))):
        plant.access_path_id = path.id
    audit.record(
        db,
        actor,
        tenant_id=order.tenant_id,
        entity="access_path",
        entity_id=path.id,
        action="create",
        new={"name": path.name, "segments": len(segments)},
    )
    return path


def _replace_segments(db: Session, path: AccessPath, segments: list[dict[str, Any]]) -> list[PathSegment]:
    for s in db.scalars(select(PathSegment).where(PathSegment.path_id == path.id)):
        db.delete(s)
    db.flush()
    out = []
    for i, item in enumerate(segments):
        seg = PathSegment(tenant_id=path.tenant_id, path_id=path.id, position=i)
        apply_values(SEGMENT, seg, {k: v for k, v in item.items() if k not in ("id", "path_id", "position")})
        seg.path_id, seg.position = path.id, i
        db.add(seg)
        out.append(seg)
    db.flush()
    return out


@router.post("/api/orders/{order_id}/paths", status_code=201, tags=["access_path"])
def add_path(order_id: uuid.UUID, data: PathIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    order = get_order(db, actor, order_id)
    path = create_path(db, actor, order, data.model_dump(), [])
    return row_dict(PATH, path)


def _get_path(db: Session, actor: Actor, path_id: uuid.UUID) -> AccessPath:
    path = db.get(AccessPath, path_id)
    if path is None or path.tenant_id != actor.tenant_id:
        raise NotFound()
    return path


@router.patch("/api/paths/{path_id}", tags=["access_path"])
def update_path(path_id: uuid.UUID, data: PathIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    path = _get_path(db, actor, path_id)
    changes = apply_values(PATH, path, data.model_dump(exclude_unset=True))
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=path.tenant_id,
            entity="access_path",
            entity_id=path.id,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    db.flush()
    order = db.get(PickupOrder, path.order_id)
    if order:
        _after_order_change(db, actor, order, changes)
    return row_dict(PATH, path)


@router.put("/api/paths/{path_id}/segments", tags=["access_path"])
def put_segments(path_id: uuid.UUID, data: SegmentsIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    path = _get_path(db, actor, path_id)
    old = [
        row_dict(SEGMENT, s)
        for s in db.scalars(
            select(PathSegment).where(PathSegment.path_id == path.id).order_by(PathSegment.position)
        )
    ]
    segs = _replace_segments(db, path, data.segments)
    audit.record(
        db,
        actor,
        tenant_id=path.tenant_id,
        entity="access_path",
        entity_id=path.id,
        action="segments",
        old=old,
        new=[row_dict(SEGMENT, s) for s in segs],
    )
    order = db.get(PickupOrder, path.order_id)
    if order:
        _after_order_change(db, actor, order, {})
    return {
        "segments": [row_dict(SEGMENT, s) for s in segs],
        "summary": path_summary(segs, path.length_confirmed_m),
    }


@router.delete("/api/paths/{path_id}", tags=["access_path"])
def delete_path(path_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    path = _get_path(db, actor, path_id)
    db.delete(path)
    audit.record(
        db, actor, tenant_id=path.tenant_id, entity="access_path", entity_id=path_id, action="delete"
    )
    return {"ok": True}

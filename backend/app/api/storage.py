"""Storage capacity of the nursery: occupied floor area by stored and expected plants."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentActor
from app.core.modules import require_module
from app.models.masterdata import StorageArea
from app.models.orders import PickupOrder, Plant
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import footprint_m2

router = APIRouter(tags=["storage"])

EXPECTED_STATUS = ("confirmed", "planned")
STORED_STATUS = ("picked_up", "stored")


def occupancy(db: Session, tenant_id: uuid.UUID, extra_plants: list[Plant] | None = None) -> dict[str, Any]:
    resolver = SettingsResolver(db, tenant_id)
    factor = float(resolver.get("general.storage_space_factor"))
    areas = list(
        db.scalars(
            select(StorageArea).where(StorageArea.tenant_id == tenant_id, StorageArea.deleted_at.is_(None))
        )
    )
    capacity = sum(a.area_m2 for a in areas)
    rows = db.execute(
        select(Plant, PickupOrder.status)
        .join(PickupOrder, PickupOrder.id == Plant.order_id)
        .where(
            Plant.tenant_id == tenant_id,
            Plant.deleted_at.is_(None),
            PickupOrder.deleted_at.is_(None),
            PickupOrder.direction == "pickup",
            PickupOrder.status.in_(EXPECTED_STATUS + STORED_STATUS),
        )
    ).all()
    stored = expected = 0.0
    per_area: dict[uuid.UUID | None, float] = {}
    frost_sensitive = 0.0
    for plant, status in rows:
        fp = footprint_m2(plant) * factor
        if status in STORED_STATUS or plant.status in ("picked_up", "stored"):
            stored += fp
        else:
            expected += fp
        per_area[plant.storage_area_id] = per_area.get(plant.storage_area_id, 0) + fp
        if plant.frost_sensitive:
            frost_sensitive += fp
    extra = sum(footprint_m2(p) * factor for p in (extra_plants or []))
    used = stored + expected + extra
    warn_pct = float(resolver.get("general.storage_warn_pct"))
    pct = (used / capacity * 100) if capacity else None
    return {
        "capacity_m2": round(capacity, 1),
        "stored_m2": round(stored, 1),
        "expected_m2": round(expected, 1),
        "extra_m2": round(extra, 1),
        "used_m2": round(used, 1),
        "pct": round(pct, 1) if pct is not None else None,
        "warn": pct is not None and pct >= warn_pct,
        "over": pct is not None and pct > 100,
        "frost_sensitive_m2": round(frost_sensitive, 1),
        "warm_capacity_m2": round(
            sum(a.area_m2 for a in areas if a.for_frost_sensitive and (a.min_temp_c or 0) >= 5), 1
        ),
        "areas": [
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "area_m2": a.area_m2,
                "assigned_m2": round(per_area.get(a.id, 0), 1),
            }
            for a in areas
        ],
        "unassigned_m2": round(per_area.get(None, 0), 1),
    }


@router.get("/api/storage/occupancy")
def get_occupancy(actor: CurrentActor, db: DB, order_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Current occupancy; with order_id the plants of a not yet confirmed order are added (acceptance check)."""
    actor.require("tenant.view")
    tid = actor.require_tenant()
    require_module(db, tid, "storage")
    extra: list[Plant] = []
    if order_id:
        order = db.get(PickupOrder, order_id)
        if (
            order is not None
            and order.tenant_id == tid
            and order.status not in EXPECTED_STATUS + STORED_STATUS
        ):
            extra = list(
                db.scalars(select(Plant).where(Plant.order_id == order.id, Plant.deleted_at.is_(None)))
            )
    return occupancy(db, tid, extra)

"""Dashboard figures that need the order tables."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.modules import module_enabled
from app.models.orders import Draft, PickupOrder, Plant


def extend(db: Session, tenant_id: uuid.UUID, out: dict[str, Any]) -> None:
    from app.api.storage import occupancy

    seasons = db.scalars(select(func.max(PickupOrder.season)).where(PickupOrder.tenant_id == tenant_id)).all()
    season = seasons[0] if seasons and seasons[0] else out["season"]
    out["season"] = season
    out["orders_by_status"] = dict(
        db.execute(
            select(PickupOrder.status, func.count())
            .where(
                PickupOrder.tenant_id == tenant_id,
                PickupOrder.season == season,
                PickupOrder.deleted_at.is_(None),
                PickupOrder.direction == "pickup",
            )
            .group_by(PickupOrder.status)
        ).all()
    )
    plant_q = (
        select(Plant.status, func.count())
        .join(PickupOrder, PickupOrder.id == Plant.order_id)
        .where(
            Plant.tenant_id == tenant_id,
            Plant.deleted_at.is_(None),
            PickupOrder.season == season,
            PickupOrder.status != "cancelled",
            PickupOrder.deleted_at.is_(None),
        )
        .group_by(Plant.status)
    )
    by_status = dict(db.execute(plant_q).all())
    out["plants_total"] = sum(by_status.values())
    out["plants_picked_up"] = by_status.get("picked_up", 0) + by_status.get("stored", 0)
    out["drafts_pending"] = (
        db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.tenant_id == tenant_id, Draft.status.in_(("review", "processing", "failed")))
        )
        or 0
    )
    out["revenue_quoted"] = float(
        db.scalar(
            select(func.coalesce(func.sum(PickupOrder.price_quoted), 0)).where(
                PickupOrder.tenant_id == tenant_id,
                PickupOrder.season == season,
                PickupOrder.status != "cancelled",
                PickupOrder.deleted_at.is_(None),
            )
        )
        or 0
    )
    if module_enabled(db, tenant_id, "storage"):
        occ = occupancy(db, tenant_id)
        out["storage"] = {
            "used_m2": occ["used_m2"],
            "capacity_m2": occ["capacity_m2"],
            "pct": occ["pct"],
            "warn": occ["warn"],
        }
    if not module_enabled(db, tenant_id, "customer_billing"):
        out["revenue_quoted"] = None
    try:
        from app.api.dashboard_tours import next_tours

        out["next_tours"] = next_tours(db, tenant_id)
        out["planned_tours"] = len(out["next_tours"])
    except ModuleNotFoundError:
        pass

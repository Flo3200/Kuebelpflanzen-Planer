"""Keeping order estimates current."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orders import PickupOrder
from app.timemodel.estimate import Estimator


def refresh_order_estimate(
    db: Session, order: PickupOrder, estimator: Estimator | None = None
) -> dict[str, Any]:
    est = (estimator or Estimator(db, order.tenant_id)).order_estimate(order)
    keep = {k: v for k, v in (order.estimate or {}).items() if k in ("photo_check", "plan_costs")}
    order.estimate = {**est, **keep}
    price = est.get("price") or {}
    if "gross" in price:
        order.price_quoted = price["gross"]
    db.flush()
    return order.estimate


def refresh_all(db: Session, tenant_id: uuid.UUID, progress=None) -> int:
    estimator = Estimator(db, tenant_id)
    orders = list(
        db.scalars(
            select(PickupOrder).where(
                PickupOrder.tenant_id == tenant_id,
                PickupOrder.deleted_at.is_(None),
                PickupOrder.status.notin_(("cancelled", "returned")),
            )
        )
    )
    for i, order in enumerate(orders):
        refresh_order_estimate(db, order, estimator)
        if progress and i % 25 == 0:
            progress(i / max(1, len(orders)))
    return len(orders)


def schedule_refresh(db: Session, tenant_id: uuid.UUID | None) -> None:
    """Queue a recomputation (one per tenant; platform changes queue all tenants)."""
    from app.jobs.queue import enqueue
    from app.models.core import Job, Tenant

    tenants = (
        [tenant_id] if tenant_id else list(db.scalars(select(Tenant.id).where(Tenant.deleted_at.is_(None))))
    )
    for tid in tenants:
        pending = db.scalar(
            select(Job.id).where(
                Job.tenant_id == tid, Job.kind == "estimates.refresh", Job.status == "queued"
            )
        )
        if pending is None:
            enqueue(db, "estimates.refresh", {}, tenant_id=tid)


ESTIMATE_GROUPS = {"staff", "team", "time", "drive", "costs", "pricing", "weight"}

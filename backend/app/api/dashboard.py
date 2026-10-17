"""Owner dashboard: season status, open drafts, planned tours, storage."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, CurrentActor
from app.api.stats import tenant_counts
from app.models.base import Base

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
def dashboard(actor: CurrentActor, db: DB) -> dict[str, Any]:
    tid = actor.require_tenant()
    actor.require("tenant.view")
    tables = Base.metadata.tables
    out: dict[str, Any] = {
        "season": date.today().year,
        "counts": tenant_counts(db, tid),
        "orders_by_status": {},
        "plants_total": 0,
        "plants_picked_up": 0,
        "drafts_pending": 0,
        "planned_tours": 0,
        "revenue_quoted": 0.0,
        "storage": None,
        "next_tours": [],
    }
    if "pickup_orders" in tables:
        from app.api.dashboard_ext import extend

        extend(db, tid, out)
    return out

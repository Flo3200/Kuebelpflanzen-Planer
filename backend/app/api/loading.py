"""Load plans: view and recompute (single tour or all tours of a plan)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.errors import NotFound
from app.jobs.queue import JobContext, enqueue, handler, run_now
from app.models.orders import Address, Customer, PickupOrder
from app.models.planning import Plan, Tour, TourStop
from app.packing.service import pack_tour
from app.packing.store import load_plan_dict
from app.settings.service import SettingsResolver

router = APIRouter(tags=["loading"])


def _tour(db, actor, tour_id: uuid.UUID) -> Tour:
    t = db.get(Tour, tour_id)
    if t is None or t.tenant_id != actor.tenant_id:
        raise NotFound()
    return t


def _tour_head(db, tour: Tour) -> dict[str, Any]:
    rows = db.execute(
        select(TourStop.position, PickupOrder.id, PickupOrder.number, Customer.name, Address.city)
        .join(PickupOrder, PickupOrder.id == TourStop.order_id)
        .join(Customer, Customer.id == PickupOrder.customer_id)
        .join(Address, Address.id == PickupOrder.address_id)
        .where(TourStop.tour_id == tour.id)
        .order_by(TourStop.position)
    ).all()
    plan = db.get(Plan, tour.plan_id)
    return {
        "id": tour.id,
        "plan_id": tour.plan_id,
        "label": tour.label,
        "date": tour.date,
        "trip_no": tour.trip_no,
        "load_status": tour.load_status,
        "load_message": tour.load_message,
        "color": tour.color,
        "vehicle": tour.unit.get("vehicle"),
        "trailer": tour.unit.get("trailer"),
        "direction": plan.direction if plan else "pickup",
        "qr_module": bool(SettingsResolver(db, tour.tenant_id).get("driver.qr_module")),
        "stops": [
            {"position": pos, "order_id": oid, "number": num, "customer": name, "city": city}
            for pos, oid, num, name, city in rows
        ],
    }


@router.get("/api/tours/{tour_id}/load-plan")
def get_load_plan(tour_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    if not (actor.has("planning.read") or actor.has("driver.app")):
        actor.require("planning.read")
    tour = _tour(db, actor, tour_id)
    return {"tour": _tour_head(db, tour), "plan": load_plan_dict(db, tour)}


@router.post("/api/tours/{tour_id}/load-plan")
def recompute_load_plan(tour_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("planning.write")
    tour = _tour(db, actor, tour_id)
    pack_tour(db, tour)
    audit.record(
        db,
        actor,
        tenant_id=tour.tenant_id,
        entity="tour",
        entity_id=tour.id,
        action="load_plan",
        new={"load_status": tour.load_status, "load_message": tour.load_message},
    )
    return {"tour": _tour_head(db, tour), "plan": load_plan_dict(db, tour)}


@handler("loading.plan_all")
def pack_all_job(ctx: JobContext) -> dict:
    plan = ctx.db.get(Plan, uuid.UUID(ctx.payload["plan_id"]))
    tours = list(
        ctx.db.scalars(
            select(Tour).where(Tour.plan_id == plan.id).order_by(Tour.date, Tour.unit_key, Tour.trip_no)
        )
    )
    ok = 0
    for i, t in enumerate(tours):
        ctx.progress(i / max(1, len(tours)), f"Ladeplan {i + 1} von {len(tours)}")
        pack_tour(ctx.db, t)
        ok += t.load_status == "ok"
    from app.planning.planner import compute_kpis

    plan.kpis = compute_kpis(ctx.db, plan)
    return {"tours": len(tours), "ok": ok}


@router.post("/api/plans/{plan_id}/load-plans")
def pack_all(plan_id: uuid.UUID, actor: CurrentActor, db: DB, sync: bool = False) -> dict[str, Any]:
    actor.require("planning.write")
    plan = db.get(Plan, plan_id)
    if plan is None or plan.tenant_id != actor.tenant_id:
        raise NotFound()
    job = enqueue(
        db, "loading.plan_all", {"plan_id": str(plan.id)}, tenant_id=plan.tenant_id, created_by=actor.user_id
    )
    if sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result}

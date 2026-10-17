"""Persisting load plans."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.i18n import t
from app.models.packing import LoadPlacement, LoadPlan
from app.models.planning import Tour


def save_load_plan(db: Session, tour: Tour, payload: dict[str, Any]) -> LoadPlan:
    db.execute(delete(LoadPlan).where(LoadPlan.tour_id == tour.id))
    ok = bool(payload.get("ok"))
    plan = LoadPlan(
        tenant_id=tour.tenant_id,
        tour_id=tour.id,
        ok=ok,
        message=payload.get("message"),
        spaces=payload.get("spaces", []),
        metrics=payload.get("metrics", {}),
        violations=payload.get("violations", []),
        unplaced=payload.get("unplaced", []),
    )
    db.add(plan)
    db.flush()
    for p in payload.get("placements", []):
        db.add(
            LoadPlacement(
                tenant_id=tour.tenant_id,
                load_plan_id=plan.id,
                plant_id=uuid.UUID(p["plant_id"]),
                order_id=uuid.UUID(p["order_id"]),
                stop_position=p["stop_position"],
                sequence=p["sequence"],
                space_id=p["space_id"],
                level=p["level"],
                orientation=p["orientation"],
                angle=p["angle"],
                x=p["x"],
                y=p["y"],
                z=p["z"],
                dims=p["dims"],
                instruction=p["instruction"],
                secure=p["secure"],
            )
        )
    tour.load_status = "ok" if ok else "failed"
    tour.load_message = None if ok else payload.get("message")
    db.flush()
    return plan


def load_plan_dict(db: Session, tour: Tour) -> dict[str, Any] | None:
    plan = db.scalar(select(LoadPlan).where(LoadPlan.tour_id == tour.id))
    if plan is None:
        return None
    from app.models.orders import Plant

    rows = list(
        db.scalars(
            select(LoadPlacement)
            .where(LoadPlacement.load_plan_id == plan.id)
            .order_by(LoadPlacement.sequence)
        )
    )
    from app.models.masterdata import Species

    ids = [r.plant_id for r in rows] + [uuid.UUID(u["plant_id"]) for u in plan.unplaced or []]
    names: dict[uuid.UUID, tuple[int, str]] = {}
    if ids:
        for p, species in db.execute(
            select(Plant, Species.name)
            .outerjoin(Species, Species.id == Plant.species_id)
            .where(Plant.id.in_(ids))
        ).all():
            names[p.id] = (p.number, f"#{p.number} {species or p.label or t('packing.plant')}")
    unplaced = [
        {**u, "label": names.get(uuid.UUID(u["plant_id"]), (None, f"#{u.get('number')}"))[1]}
        for u in plan.unplaced or []
    ]
    return {
        "id": plan.id,
        "tour_id": tour.id,
        "ok": plan.ok,
        "message": plan.message,
        "spaces": plan.spaces,
        "metrics": plan.metrics,
        "violations": plan.violations,
        "unplaced": unplaced,
        "created_at": plan.created_at,
        "placements": [
            {
                "id": r.id,
                "plant_id": r.plant_id,
                "number": names.get(r.plant_id, (None, ""))[0],
                "label": names.get(r.plant_id, (None, ""))[1],
                "order_id": r.order_id,
                "stop_position": r.stop_position,
                "sequence": r.sequence,
                "space_id": r.space_id,
                "level": r.level,
                "orientation": r.orientation,
                "angle": r.angle,
                "x": r.x,
                "y": r.y,
                "z": r.z,
                "dims": r.dims,
                "instruction": r.instruction,
                "secure": r.secure,
                "loaded_at": r.loaded_at,
            }
            for r in rows
        ],
    }

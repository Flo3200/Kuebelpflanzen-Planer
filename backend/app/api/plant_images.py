"""Plant images: a real photo or, without one, an AI image (marked "KI-Bild")."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.ai.images import generate_for_plant, plant_image
from app.api.deps import DB, CurrentActor
from app.core.errors import NotFound
from app.jobs.queue import enqueue, run_now
from app.models.orders import PickupOrder, Plant

router = APIRouter(tags=["plant-images"])


class ImagesIn(BaseModel):
    force: bool = False
    sync: bool = False


@router.post("/api/orders/{order_id}/plant-images")
def order_images(order_id: uuid.UUID, data: ImagesIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    o = db.get(PickupOrder, order_id)
    if o is None or o.tenant_id != actor.tenant_id:
        raise NotFound()
    job = enqueue(
        db,
        "ai.plant_images",
        {"order_id": str(o.id), "force": data.force},
        tenant_id=o.tenant_id,
        created_by=actor.user_id,
    )
    if data.sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result}


@router.post("/api/plants/{plant_id}/image")
def plant_image_now(plant_id: uuid.UUID, data: ImagesIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """New AI image for one plant right away (e.g. after the size was corrected)."""
    actor.require("orders.write")
    p = db.get(Plant, plant_id)
    if p is None or p.tenant_id != actor.tenant_id:
        raise NotFound()
    generate_for_plant(db, p, force=data.force)
    return {"image": plant_image(db, p)}

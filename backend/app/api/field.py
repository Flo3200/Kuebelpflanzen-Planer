"""Dispatcher view of field data: measurements (mark outliers) and deviation reports (apply/dismiss)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentActor
from app.api.driver import deviation_dict
from app.core import audit
from app.core.errors import AppError, NotFound
from app.models.field import Deviation, Measurement
from app.models.orders import AccessPath, PickupOrder, Plant
from app.timemodel.service import refresh_order_estimate

router = APIRouter(tags=["field"])


def measurement_dict(m: Measurement, number: str | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "order_id": m.order_id,
        "order_number": number,
        "tour_id": m.tour_id,
        "stop_id": m.stop_id,
        "date": m.date,
        "source": m.source,
        "team_size": m.team_size,
        "member_ids": m.member_ids,
        "drive_min": m.drive_min,
        "fixed_min": m.fixed_min,
        "carry_min": m.carry_min,
        "duration_min": m.duration_min,
        "break_min": m.break_min,
        "per_plant": m.per_plant,
        "predicted_min": m.predicted_min,
        "experiment": m.experiment,
        "excluded": m.excluded,
        "exclude_reason": m.exclude_reason,
        "features": m.features,
        "deviations": m.deviations,
    }


@router.get("/api/measurements")
def list_measurements(
    actor: CurrentActor, db: DB, source: str | None = None, limit: int = 500
) -> dict[str, Any]:
    actor.require("planning.read")
    q = (
        select(Measurement, PickupOrder.number)
        .join(PickupOrder, PickupOrder.id == Measurement.order_id)
        .where(Measurement.tenant_id == actor.tenant_id)
    )
    if source:
        q = q.where(Measurement.source == source)
    rows = db.execute(
        q.order_by(Measurement.date.desc(), Measurement.created_at.desc()).limit(min(limit, 5000))
    ).all()
    counts = dict(
        db.execute(
            select(Measurement.source, func.count())
            .where(Measurement.tenant_id == actor.tenant_id)
            .group_by(Measurement.source)
        ).all()
    )
    return {"items": [measurement_dict(m, n) for m, n in rows], "counts": counts}


class MeasurementPatch(BaseModel):
    excluded: bool
    exclude_reason: str | None = Field(default=None, max_length=200)


@router.patch("/api/measurements/{measurement_id}")
def patch_measurement(
    measurement_id: uuid.UUID, data: MeasurementPatch, actor: CurrentActor, db: DB
) -> dict[str, Any]:
    actor.require("model.fit")
    m = db.get(Measurement, measurement_id)
    if m is None or m.tenant_id != actor.tenant_id:
        raise NotFound()
    old = {"excluded": m.excluded, "exclude_reason": m.exclude_reason}
    m.excluded = data.excluded
    m.exclude_reason = data.exclude_reason if data.excluded else None
    audit.record(
        db,
        actor,
        tenant_id=m.tenant_id,
        entity="measurement",
        entity_id=m.id,
        action="update",
        old=old,
        new={"excluded": m.excluded, "exclude_reason": m.exclude_reason},
        undoable=True,
    )
    return measurement_dict(m)


@router.get("/api/deviations")
def list_deviations(
    actor: CurrentActor, db: DB, status: str | None = "open", order_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    actor.require("orders.read")
    q = select(Deviation).where(Deviation.tenant_id == actor.tenant_id)
    if status:
        q = q.where(Deviation.status == status)
    if order_id:
        q = q.where(Deviation.order_id == order_id)
    return [deviation_dict(db, d) for d in db.scalars(q.order_by(Deviation.created_at.desc()).limit(500))]


class DecisionIn(BaseModel):
    action: str = Field(pattern="^(apply|dismiss)$")
    values: dict[str, float] | None = None  # corrected values to apply (default: the reported ones)


PLANT_FIELDS = {
    "weight_kg": "weight_measured_kg",
    "height_cm": "total_height_cm",
    "crown_width_cm": "crown_width_cm",
    "pot_diameter_cm": "pot_diameter_cm",
}


@router.post("/api/deviations/{deviation_id}/decide")
def decide(deviation_id: uuid.UUID, data: DecisionIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Apply: reported values go into plant/path data (estimate recomputed, replanning hint); dismiss: nothing changes."""
    actor.require("orders.write")
    d = db.get(Deviation, deviation_id)
    if d is None or d.tenant_id != actor.tenant_id:
        raise NotFound()
    if d.status != "open":
        raise AppError("errors.already_decided", status_code=409)
    changes: dict[str, Any] = {}
    if data.action == "apply":
        values = {**d.values, **(data.values or {})}
        order = db.get(PickupOrder, d.order_id)
        if d.kind in ("plant_heavier", "plant_bigger") and d.plant_id:
            plant = db.get(Plant, d.plant_id)
            if plant is not None:
                for key, attr in PLANT_FIELDS.items():
                    if key in values and values[key]:
                        changes[attr] = {"old": getattr(plant, attr), "new": float(values[key])}
                        setattr(plant, attr, float(values[key]))
        if d.kind == "path_different" and values.get("path_length_m"):
            path = db.scalar(
                select(AccessPath)
                .where(AccessPath.order_id == (order.return_of_id or order.id))
                .order_by(AccessPath.created_at)
            )
            if path is not None:
                changes["path_length_m"] = {
                    "old": path.length_confirmed_m,
                    "new": float(values["path_length_m"]),
                }
                path.length_confirmed_m = float(values["path_length_m"])
        if d.kind == "customer_absent" and d.stop_id:
            m = db.scalar(select(Measurement).where(Measurement.stop_id == d.stop_id))
            if m is not None:
                m.excluded = True
                m.exclude_reason = "customer_absent"
                changes["measurement_excluded"] = str(m.id)
        if changes and order is not None:
            refresh_order_estimate(db, order)
            from app.api.planning import mark_needs_replan

            mark_needs_replan(db, order.tenant_id, f"deviation:{order.number}", order.direction)
    d.status = "applied" if data.action == "apply" else "dismissed"
    d.decided_by = actor.user_id
    d.decided_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        tenant_id=d.tenant_id,
        entity="deviation",
        entity_id=d.id,
        action=data.action,
        new=changes or None,
    )
    return {**deviation_dict(db, d), "changes": changes}


# ---------------------------------------------------------------- QR labels (optional module)


def _labels_for_orders(db, orders: list[PickupOrder], extra: dict[uuid.UUID, str] | None = None):
    from app.models.orders import Customer
    from app.pdf.labels import Label

    out = []
    for o in orders:
        customer = db.get(Customer, o.customer_id)
        source = o.return_of_id or o.id
        for p in db.scalars(
            select(Plant).where(Plant.order_id == source, Plant.deleted_at.is_(None)).order_by(Plant.number)
        ):
            out.append(
                Label(
                    str(p.id),
                    p.number,
                    p.species_name or p.label or "",
                    customer.name if customer else "",
                    o.number,
                    (extra or {}).get(o.id, ""),
                )
            )
    return out


def _require_qr(db, actor) -> None:
    from app.settings.service import SettingsResolver

    if not bool(SettingsResolver(db, actor.tenant_id).get("driver.qr_module")):
        raise AppError("errors.module_off", status_code=409)


@router.get("/api/orders/{order_id}/labels.pdf")
def order_labels(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> Response:
    actor.require("orders.read")
    _require_qr(db, actor)
    order = db.get(PickupOrder, order_id)
    if order is None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    from app.pdf.labels import labels_pdf

    pdf = labels_pdf(_labels_for_orders(db, [order]), f"Etiketten {order.number}")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etiketten-{order.number}.pdf"'},
    )


@router.get("/api/tours/{tour_id}/labels.pdf")
def tour_labels(tour_id: uuid.UUID, actor: CurrentActor, db: DB) -> Response:
    actor.require("planning.read")
    _require_qr(db, actor)
    from app.models.planning import Tour, TourStop
    from app.pdf.labels import labels_pdf

    tour = db.get(Tour, tour_id)
    if tour is None or tour.tenant_id != actor.tenant_id:
        raise NotFound()
    stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == tour.id).order_by(TourStop.position)))
    orders = [db.get(PickupOrder, s.order_id) for s in stops]
    extra = {s.order_id: f"Tour {tour.date:%d.%m.} · Stopp {s.position}" for s in stops}
    pdf = labels_pdf(_labels_for_orders(db, [o for o in orders if o], extra), f"Etiketten {tour.label}")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="etiketten-tour.pdf"'},
    )

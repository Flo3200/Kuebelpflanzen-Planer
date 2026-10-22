"""Ending a tour early (round 2, package R; setting planning.abort_enabled, off by default).

In addition to the planning buffer: when a tour runs far behind (traffic, breakdown, illness, weather)
the team ends it. Stops not yet started are skipped and their orders go back to "confirmed", so the
next planning run takes them again; the office gets a notification and the plan a replanning hint.
Stops that are already in progress stay as they are.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError
from app.i18n import t
from app.models.masterdata import Vehicle
from app.models.orders import PickupOrder
from app.models.planning import Plan, Tour, TourStop
from app.settings.service import SettingsResolver

REASONS = ("late", "vehicle", "weather", "illness", "customer", "other")


def movable(order: PickupOrder | None, day) -> bool:
    """A stop can be postponed if the order has no fixed date and its latest date is after the day."""
    if order is None or order.fixed_date is not None:
        return False
    return order.latest_date is None or order.latest_date > day


def abort_tour(db: Session, actor: Actor, tour: Tour, reason: str, note: str | None = None) -> dict[str, Any]:
    r = SettingsResolver(db, tour.tenant_id)
    if not r.get("planning.abort_enabled"):
        raise AppError("errors.abort_disabled", status_code=409)
    if reason not in REASONS:
        raise AppError("errors.validation")
    skipped = []
    for s in db.scalars(select(TourStop).where(TourStop.tour_id == tour.id).order_by(TourStop.position)):
        if s.status != "planned":
            continue  # arrived, carrying, loaded or done: the team finishes it
        s.status = "skipped"
        o = db.get(PickupOrder, s.order_id)
        if o is not None and o.status == "planned":
            o.status = "confirmed"  # back to planning
        skipped.append({"stop_id": str(s.id), "order_id": str(s.order_id), "number": o.number if o else None})
    tour.changed_at = datetime.now(UTC)
    plan = db.get(Plan, tour.plan_id)
    from app.api.planning import mark_needs_replan
    from app.notify.service import notify

    mark_needs_replan(db, tour.tenant_id, f"abort:{tour.id}", plan.direction if plan else "pickup")
    v = db.get(Vehicle, tour.vehicle_id) if tour.vehicle_id else None
    label = f"{v.name if v else 'Tour'} {tour.date.strftime('%d.%m.')}"
    reason_text = t(f"abort_reasons.{reason}", _default=reason) + (f" – {note}" if note else "")
    notify(
        db,
        tour.tenant_id,
        "tour_aborted",
        t("notifications.tour_aborted", tour=label),
        body=t("notifications.tour_aborted_body", n=len(skipped), reason=reason_text),
        link="/betrieb/planung",
        data={"tour_id": str(tour.id), "skipped": skipped, "reason": reason, "note": note},
        replace_open=False,
    )
    audit.record(
        db,
        actor,
        tenant_id=tour.tenant_id,
        entity="tour",
        entity_id=tour.id,
        action="abort",
        new={"reason": reason, "note": note, "skipped": [x["number"] for x in skipped]},
    )
    db.flush()
    return {"tour_id": tour.id, "skipped": skipped, "reason": reason}

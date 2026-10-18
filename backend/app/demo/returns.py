"""Demo step: a quarter of the pickups is already picked up and stored (with storage area), and
their spring returns exist (April to May of the next year), so a return plan can be computed."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.core.context import system_actor
from app.demo.generator import step
from app.models.masterdata import Species, StorageArea
from app.models.orders import PickupOrder, Plant
from app.timemodel.estimate import Estimator
from app.timemodel.service import refresh_order_estimate


@step
def returns(db, tenant, rng, options, report, spec) -> None:
    if not getattr(options, "returns", True):
        return
    from app.api.orders import make_return

    orders = list(
        db.scalars(
            select(PickupOrder)
            .where(
                PickupOrder.tenant_id == tenant.id,
                PickupOrder.direction == "pickup",
                PickupOrder.status == "confirmed",
            )
            .order_by(PickupOrder.number)
        )
    )
    areas = list(db.scalars(select(StorageArea).where(StorageArea.tenant_id == tenant.id)))
    warm = [a for a in areas if a.for_frost_sensitive] or areas
    cold = [a for a in areas if not a.for_frost_sensitive] or areas
    stored = [o for o in orders if rng.random() < 0.25]
    actor = system_actor(tenant.id, label="Demodaten")
    year = (stored[0].season if stored and stored[0].season else date.today().year) + 1
    est = Estimator(db, tenant.id)
    created = 0
    for o in stored:
        o.status = "stored"
        for p in db.scalars(select(Plant).where(Plant.order_id == o.id, Plant.deleted_at.is_(None))):
            p.status = "stored"
            # half-hardy plants (frost_sensitive False) prefer the warm area as well
            sp = db.get(Species, p.species_id) if p.species_id else None
            sensitive = bool(p.frost_sensitive) or (sp is not None and sp.frost_sensitivity != "hardy")
            pool = warm if sensitive else cold
            if pool:
                p.storage_area_id = rng.choice(pool).id
        start = date(year, 4, 1) if rng.random() < 0.7 else date(year, 4, 20)
        ret, new = make_return(db, actor, o, start, date(year, 5, 31))
        if new:
            refresh_order_estimate(db, ret, est)
            created += 1
    db.flush()
    report["returns"] = created

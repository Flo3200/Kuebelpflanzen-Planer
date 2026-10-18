"""Synthetic measurements from known "true" parameters (demo data and the phase 6 acceptance test).

Durations are computed with the active time formula, the true parameters and true personal speed
factors, then multiplied by lognormal noise. A fit should find the true values again.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formula.store import load_active
from app.learning.fit import base_params
from app.models.field import Measurement
from app.models.masterdata import StaffMember
from app.models.orders import PickupOrder
from app.timemodel.estimate import Estimator


def generate(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    n: int,
    true_params: dict[str, float] | None = None,
    true_staff: dict[str, float] | None = None,
    noise_sigma: float = 0.12,
    outlier_share: float = 0.0,
    per_plant: bool = False,
    seed: int = 1,
    start: date | None = None,
    tier: int = 1,
) -> dict[str, Any]:
    rng = random.Random(seed)
    formula = load_active(db, tenant_id, "time", tier)
    params = {**base_params(formula), **(true_params or {})}
    est = Estimator(db, tenant_id, time_formula=formula)
    staff = [
        str(s.id)
        for s in db.scalars(
            select(StaffMember)
            .where(StaffMember.tenant_id == tenant_id, StaffMember.deleted_at.is_(None))
            .order_by(StaffMember.name, StaffMember.id)
        )
    ]
    if true_staff is None:
        # relative to the average worker: mean 1 (the same convention as the fit)
        raw = {s: rng.uniform(0.8, 1.25) for s in staff}
        mean = sum(raw.values()) / max(1, len(raw))
        true_staff = {s: round(v / mean, 3) for s, v in raw.items()}
    orders = list(
        db.scalars(
            select(PickupOrder)
            .where(
                PickupOrder.tenant_id == tenant_id,
                PickupOrder.deleted_at.is_(None),
                PickupOrder.status != "cancelled",
            )
            .order_by(PickupOrder.number)
        )
    )
    rng.shuffle(orders)
    start = start or date(2025, 10, 6)
    made = 0
    cache: dict[uuid.UUID, Any] = {}
    max_size = int(est.resolver.get("team.max_size"))
    for k in range(n * 3):
        if made >= n or not orders:
            break
        order = orders[k % len(orders)]
        if order.id not in cache:
            paths = est.paths_for(order)
            plants = est.plants_of(order)
            cache[order.id] = [est.plant_calc(p, paths.get(p.access_path_id) or paths[None]) for p in plants]
        calcs = cache[order.id]
        if not calcs:
            continue
        need = max(c.crew.crew for c in calcs)
        # varied team sizes (as in experiment mode) so the effect of the team can be learned
        team = min(max_size, need + rng.choice([0, 0, 0, 1, 1, 2]))
        members = rng.sample(staff, k=min(team, len(staff))) if staff else []
        speed = sum(true_staff.get(m, 1.0) for m in members) / max(1, len(members))
        true = est.stop_duration(calcs, team, speed, params)
        measured = true * rng.lognormvariate(0, noise_sigma)
        if outlier_share and rng.random() < outlier_share:
            measured *= rng.choice([2.5, 3.0, 0.35])
        per = []
        if per_plant:
            for c in calcs:
                work = float(c.vars.get("work") or 0)
                per.append(
                    {
                        "plant_id": str(c.plant.id),
                        "minutes": round(work / team / speed * rng.lognormvariate(0, noise_sigma), 2),
                    }
                )
        day = start + timedelta(days=made // 6)
        db.add(
            Measurement(
                tenant_id=tenant_id,
                order_id=order.id,
                date=day,
                source="synthetic",
                team_size=team,
                member_ids=members,
                duration_min=round(measured, 2),
                fixed_min=None,
                carry_min=None,
                per_plant=per,
                predicted_min=None,
                experiment=team > need,
                features={"true_min": round(true, 2)},
            )
        )
        made += 1
    db.flush()
    return {"created": made, "true_params": params, "true_staff": true_staff}

"""Turn measurements into fitting samples: formula variables per plant and stop, measured minutes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formula.store import CompiledFormula
from app.models.field import Deviation, Measurement
from app.models.orders import PickupOrder
from app.timemodel.estimate import Estimator


@dataclass
class Sample:
    measurement_id: str
    order_number: str
    measured: float
    team: int
    members: list[str]
    stop_vars: dict[str, float]
    plants: list[dict[str, Any]]
    plant_ids: list[str]
    per_plant: list[tuple[int, float]]  # (index into plants, minutes)
    features: dict[str, Any]
    experiment: bool = False
    used: bool = True  # False: excluded (outlier, customer absent) - shown, not fitted
    exclude_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def predict(self, formula: CompiledFormula, params: dict[str, float], speed: float = 1.0) -> float:
        out = formula.run(
            {**self.stop_vars, "speed": max(0.1, speed)}, [dict(p) for p in self.plants], params
        )
        return max(0.0, float(out["duration"]))

    def plant_work(
        self, formula: CompiledFormula, params: dict[str, float], speed: float = 1.0
    ) -> list[float]:
        plants = [dict(p) for p in self.plants]
        formula.run({**self.stop_vars, "speed": max(0.1, speed)}, plants, params)
        return [float(p.get("work") or 0.0) for p in plants]


def features_of(
    stop_vars: dict[str, float], plants: list[dict[str, Any]], team: int, experiment: bool
) -> dict[str, Any]:
    return {
        "total_weight": round(stop_vars["total_weight"], 1),
        "n_plants": len(plants),
        "stairs": any(p.get("has_stairs") for p in plants),
        "path_length": round(max((p.get("path_length") or 0) for p in plants), 1) if plants else 0.0,
        "height_meters": round(max((p.get("height_meters") or 0) for p in plants), 1) if plants else 0.0,
        "narrow": any((p.get("narrow_factor") or 1) > 1 for p in plants),
        "team": team,
        "experiment": experiment,
    }


def prepare_samples(
    db: Session, tenant_id: uuid.UUID, est: Estimator, include_excluded: bool = True
) -> list[Sample]:
    """One sample per measurement; variables come from the current plant and path data."""
    absent = {
        d.stop_id
        for d in db.scalars(
            select(Deviation).where(
                Deviation.tenant_id == tenant_id,
                Deviation.kind == "customer_absent",
                Deviation.status != "dismissed",
            )
        )
    }
    out: list[Sample] = []
    rows = db.execute(
        select(Measurement, PickupOrder)
        .join(PickupOrder, PickupOrder.id == Measurement.order_id)
        .where(Measurement.tenant_id == tenant_id)
        .order_by(Measurement.date, Measurement.created_at)
    ).all()
    walk = float(est.resolver.get("time.walk_speed_m_min"))
    for m, order in rows:
        used = not m.excluded and m.stop_id not in absent and m.duration_min > 0
        if not used and not include_excluded:
            continue
        paths = est.paths_for(order)
        plants = est.plants_of(order)
        if not plants:
            continue
        calcs = [est.plant_calc(p, paths.get(p.access_path_id) or paths[None]) for p in plants]
        team = max(1, int(m.team_size or 1))
        stop_vars = {
            "team": float(team),
            "speed": 1.0,
            "n_plants": float(len(calcs)),
            "total_weight": sum(c.vars["weight"] for c in calcs),
            "walk_speed": walk,
            "max_crew": float(max(c.crew.crew for c in calcs)),
        }
        plant_vars = [dict(c.vars) for c in calcs]
        ids = [str(c.plant.id) for c in calcs]
        per_plant = []
        for pp in m.per_plant or []:
            if pp.get("plant_id") in ids and pp.get("minutes") is not None:
                per_plant.append((ids.index(pp["plant_id"]), float(pp["minutes"])))
        reason = m.exclude_reason or ("customer_absent" if m.stop_id in absent else None)
        out.append(
            Sample(
                measurement_id=str(m.id),
                order_number=order.number,
                measured=float(m.duration_min),
                team=team,
                members=[str(x) for x in m.member_ids or []],
                stop_vars=stop_vars,
                plants=plant_vars,
                plant_ids=ids,
                per_plant=per_plant,
                features=features_of(stop_vars, plant_vars, team, m.experiment),
                experiment=m.experiment,
                used=used,
                exclude_reason=reason if not used else None,
                extra={"source": m.source, "date": str(m.date)},
            )
        )
    return out

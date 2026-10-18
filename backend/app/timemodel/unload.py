"""Unloading time at the depot after a trip (package F).

The formula "unload" (formula editor, learnable) gives the minutes from the plants of the trip and
the team: start formula u_fixed + (u_plant · n_plants + u_kg · total_weight) / team. With
planning.unload_mode = fixed (or if the formula cannot be evaluated) the fixed planning.unload_min
applies. The solver works with an estimate for a typical full trip of each unit; after solving every
trip gets its exact unloading window.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.formula.parser import FormulaError
from app.formula.store import CompiledFormula, load_active
from app.settings.service import SettingsResolver


class UnloadModel:
    def __init__(self, db: Session, tenant_id: uuid.UUID, resolver: SettingsResolver | None = None) -> None:
        self.r = resolver or SettingsResolver(db, tenant_id)
        self.formula: CompiledFormula | None
        try:
            self.formula = load_active(db, tenant_id, "unload", 1)
        except Exception:  # noqa: BLE001 - no formula seeded yet: fixed minutes
            self.formula = None

    def fixed(self, vehicle_id: str | uuid.UUID | None = None) -> float:
        chain = (
            [("vehicle", uuid.UUID(str(vehicle_id)))]
            if vehicle_id and "virtual" not in str(vehicle_id)
            else []
        )
        return float(self.r.get("planning.unload_min", *chain))

    def mode(self, vehicle_id: str | uuid.UUID | None = None) -> str:
        chain = (
            [("vehicle", uuid.UUID(str(vehicle_id)))]
            if vehicle_id and "virtual" not in str(vehicle_id)
            else []
        )
        return str(self.r.get("planning.unload_mode", *chain))

    def minutes(
        self,
        weights: list[float],
        team: int,
        *,
        n_stops: int = 1,
        heights: list[float] | None = None,
        vehicle_id: str | uuid.UUID | None = None,
        params: dict[str, float] | None = None,
    ) -> float:
        if self.formula is None or self.mode(vehicle_id) != "formula":
            return self.fixed(vehicle_id)
        plants: list[dict[str, Any]] = [
            {
                "weight": float(w or 0),
                "height": float((heights or [])[i] if heights and i < len(heights) else 0),
            }
            for i, w in enumerate(weights)
        ]
        stop_vars = {
            "n_plants": len(weights),
            "total_weight": float(sum(w or 0 for w in weights)),
            "max_weight": float(max(weights, default=0) or 0),
            "team": max(1, int(team)),
            "n_stops": max(1, int(n_stops)),
        }
        try:
            out = self.formula.run(stop_vars, plants, params)
            return max(0.0, round(float(out["unload"]), 1))
        except (FormulaError, KeyError, TypeError, ValueError, ZeroDivisionError):
            return self.fixed(vehicle_id)

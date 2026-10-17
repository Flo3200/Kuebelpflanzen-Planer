"""Required team size per plant (section 7.3). The strictest rule wins; path rules add persons.

Rules:
  weight   – more persons when the plant is heavier than the solo carry weight; team capacity =
             carry factor × sum of the members' solo carry weights
  grip     – from a pot diameter or plant height on, never alone
  path     – stairs (heavy plants), steep slopes and narrow passages add persons
  equipment– usable equipment (capacity, stairs, surfaces, width) raises the solo limit
  override – a value entered for the plant replaces the computed size
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EquipmentInfo:
    id: str
    name: str
    kind: str
    capacity_kg: float | None
    carry_time_factor: float
    solo_limit_kg: float | None
    usable_on_stairs: bool
    surfaces: list[str]
    min_path_width_cm: float | None
    vehicle_id: str | None
    cost_per_use: float = 0.0


@dataclass
class PathInfo:
    length_m: float
    carry_height_m: float
    steps: int
    min_width_cm: float | None
    doors: int
    max_slope_pct: float
    has_stairs: bool
    elevator: bool
    surfaces: list[str]


@dataclass
class CrewRules:
    solo_kg: float
    carry_factor: float
    grip_diameter_cm: float
    grip_height_cm: float
    stairs_weight_kg: float
    stairs_extra: int
    steep_slope_pct: float
    narrow_extra: int
    max_size: int


@dataclass
class CrewResult:
    crew: int
    reasons: list[str] = field(default_factory=list)
    equipment: EquipmentInfo | None = None
    exceeds_max: bool = False
    needed: int = 0


def equipment_usable(eq: EquipmentInfo, weight: float, path: PathInfo) -> bool:
    if eq.capacity_kg is not None and weight > eq.capacity_kg:
        return False
    if path.has_stairs and not eq.usable_on_stairs:
        return False
    if eq.surfaces and any(s not in eq.surfaces for s in path.surfaces):
        return False
    if eq.min_path_width_cm and path.min_width_cm and path.min_width_cm < eq.min_path_width_cm:
        return False
    return True


def persons_for_weight(weight: float, solo_limits: list[float], factor: float) -> int:
    """Smallest team that can carry the weight. solo_limits sorted descending (one per member,
    or a single default value that stands for every person)."""
    if not solo_limits:
        return 1
    limits = sorted(solo_limits, reverse=True)
    if weight <= limits[0]:
        return 1
    if len(limits) == 1:
        per = max(limits[0] * factor, 0.1)
        return max(2, math.ceil(weight / per))
    for n in range(2, len(limits) + 1):
        if factor * sum(limits[:n]) >= weight:
            return n
    # more people than members given: extend with the weakest member's value
    total = factor * sum(limits)
    extra = math.ceil((weight - total) / max(limits[-1] * factor, 0.1))
    return len(limits) + max(1, extra)


def required_crew(
    weight: float,
    pot_diameter_cm: float,
    height_cm: float,
    path: PathInfo,
    rules: CrewRules,
    equipment: list[EquipmentInfo],
    narrow: bool,
    override: int | None = None,
    solo_limits: list[float] | None = None,
) -> CrewResult:
    limits = solo_limits or [rules.solo_kg]
    usable = [e for e in equipment if equipment_usable(e, weight, path)]
    base = persons_for_weight(weight, limits, rules.carry_factor)
    reasons = ["weight"] if base > 1 else []
    chosen: EquipmentInfo | None = None
    if base > 1 and usable:
        # equipment raises the solo limit; take the one that saves most persons, then the fastest
        best = None
        for e in usable:
            boosted = [max(x, e.solo_limit_kg or 0) for x in limits]
            n = persons_for_weight(weight, boosted, rules.carry_factor)
            key = (n, e.carry_time_factor)
            if best is None or key < best[0]:
                best = (key, e)
        if best is not None and best[0][0] < base:
            base = best[0][0]
            chosen = best[1]
            reasons.append("equipment")
    if chosen is None and usable:
        chosen = min(usable, key=lambda e: e.carry_time_factor)
        if chosen.carry_time_factor >= 1.0:
            chosen = None
    n = base
    if pot_diameter_cm >= rules.grip_diameter_cm:
        if n < 2:
            reasons.append("grip_diameter")
        n = max(n, 2)
    if height_cm >= rules.grip_height_cm:
        if n < 2:
            reasons.append("grip_height")
        n = max(n, 2)
    stair_climber = chosen is not None and chosen.kind == "stair_climber"
    if path.has_stairs and weight > rules.stairs_weight_kg and not stair_climber and rules.stairs_extra:
        n += rules.stairs_extra
        reasons.append("stairs")
    if path.max_slope_pct >= rules.steep_slope_pct and weight > limits[0]:
        n += 1
        reasons.append("steep")
    if narrow and rules.narrow_extra:
        n += rules.narrow_extra
        reasons.append("narrow")
    needed = n
    exceeds = False
    if n > rules.max_size:
        exceeds = True
        n = rules.max_size
        reasons.append("max_size")
    if override:
        n = int(override)
        reasons = ["override"]
    return CrewResult(crew=max(1, n), reasons=reasons, equipment=chosen, exceeds_max=exceeds, needed=needed)


def summary_reasons(results: list[CrewResult]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in results:
        for x in r.reasons:
            counts[x] = counts.get(x, 0) + 1
    return counts

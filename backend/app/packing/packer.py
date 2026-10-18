"""Load planner: extreme-point placement ("deepest free corner") + simulated annealing.

The loading sequence follows the tour: for pickups the first stop is loaded first and ends up
deepest (front wall), the last stop near the door; for returns (deliveries) the order is
reversed. Simulated annealing permutes plants within a stop and changes the orientation of
tiltable plants; every state is decoded by the placement heuristic and scored.

The packer is independent of the database; app.packing.service builds its input.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from app.i18n import t
from app.packing.geometry import (
    Orientation,
    Placement,
    PlantItem,
    Space,
    crown_conflict,
    crown_inside_walls,
    rigid_conflict,
)


@dataclass
class PackSettings:
    clearance: float = 2.0
    heavy_kg: float = 40.0
    cog_tolerance: float = 0.15
    tall_ratio: float = 3.0
    time_limit_s: float = 3.0
    sort_rule: str = "tour_then_size"
    direction: str = "pickup"
    seed: int = 1


@dataclass
class StartLayout:
    """A proposed arrangement (package G, from the AI): loading order, orientation and position per
    plant. The packer uses it as its start solution: every proposed position is checked with all
    rules and only kept if valid; the annealing then improves the order and orientations."""

    sequence: list[str] = field(default_factory=list)  # plant ids in loading order
    orientation: dict[str, str] = field(default_factory=dict)  # plant id -> upright | lying_x | ...
    positions: dict[str, tuple[str, float, float, str]] = field(default_factory=dict)  # (space, x, y, level)
    source: str = "ai"


@dataclass
class PackResult:
    ok: bool
    placements: list[Placement]
    unplaced: list[dict[str, Any]]
    metrics: dict[str, Any]
    violations: list[str]
    message: str
    iterations: int = 0
    score: float = 0.0
    instructions: dict[str, dict[str, Any]] = field(default_factory=dict)


def pack_message(
    ok: bool, unplaced: list[dict[str, Any]], hard_viol: list[str], items: dict[str, PlantItem]
) -> str:
    """German explanation of the result: which plants do not fit and why, or which load limit is exceeded."""
    if ok:
        return t("packing.ok")
    if unplaced:
        parts = []
        for u in unplaced[:6]:
            it = items.get(u["plant_id"])
            name = it.label if it else f"#{u['number']}"
            parts.append(f"{name} ({t('packing.reasons.' + u['reason'], _default=u['reason'])})")
        if len(unplaced) > 6:
            parts.append("…")
        return t("packing.not_placed", count=len(unplaced), items=", ".join(parts))
    names = [t("packing.violations." + v.split(":")[0], _default=v) for v in sorted(set(hard_viol))]
    return t("packing.axle", items=", ".join(names))


class Packer:
    def __init__(self, spaces: list[Space], settings: PackSettings) -> None:
        self.spaces = spaces
        self.s = settings
        self.rng = random.Random(settings.seed)
        self.hints: dict[str, tuple[str, float, float, str]] = {}  # proposed positions (StartLayout)
        self.hints_used = 0

    # ------------------------------------------------------------------ static checks

    def loadable(self, item: PlantItem) -> str | None:
        """Reason why the item can never be loaded into any space (door, height), else None."""
        reasons = []
        for sp in self.spaces:
            passage = item.passage_width()
            if item.pot_radius * 2 > sp.door_w or item.pot_radius * 2 > sp.width:
                reasons.append("door_width")
                continue
            fits_upright = item.total_h <= sp.height and (item.total_h <= sp.door_h + 15 or item.can_tilt)
            fits_lying = (
                item.can_tilt
                and item.tilt_max_deg >= 60
                and item.total_h <= sp.length
                and passage <= sp.height
            )
            if fits_upright or fits_lying:
                return None
            reasons.append("height")
        return reasons[0] if reasons else "no_space"

    # ------------------------------------------------------------------ placement

    def _valid(self, p: Placement, sp: Space, placed: list[Placement], shelf_loads: dict[str, float]) -> bool:
        x0, y0, x1, y1 = p.rigid_rect()
        if x0 < -0.5 or y0 < -0.5 or x1 > sp.length + 0.5 or y1 > sp.width + 0.5:
            return False
        if p.level == "floor":
            if p.top() > sp.height + 0.01:
                return False
            px0, py0, px1, py1 = p.pot_rect()
            lying_h = p.item.bounding(p.orientation)[2] if p.orientation.name != "upright" else 0.0
            for ob in sp.obstacles:
                if ob.overlaps(px0, py0, px1, py1):
                    return False
                # the crown of a lying plant may rest over low obstacles
                if p.orientation.name != "upright" and ob.overlaps(x0, y0, x1, y1) and ob.z1 > lying_h * 0.5:
                    return False
            for sh in sp.shelves:
                if (
                    sh.blocks_floor
                    and x0 < sh.x0 + sh.length - 0.5
                    and sh.x0 < x1 - 0.5
                    and y0 < sh.y0 + sh.depth - 0.5
                    and sh.y0 < y1 - 0.5
                ):
                    if p.top() > sh.z:
                        return False
        else:
            sh = next(s for s in sp.shelves if s.id == p.level)
            if x0 < sh.x0 or x1 > sh.x0 + sh.length or y0 < sh.y0 or y1 > sh.y0 + sh.depth:
                return False
            if p.top() > sh.z + sh.clearance or shelf_loads.get(sh.id, 0) + p.item.weight > sh.max_load:
                return False
        if not crown_inside_walls(p, sp):
            return False
        others = [q for q in placed if q.space_id == p.space_id]
        for q in others:
            if rigid_conflict(p, q, self.s.clearance):
                return False
        for q in others:
            if crown_conflict(p, q):
                return False
        return True

    @staticmethod
    def _extent(item: PlantItem, orient: Orientation) -> tuple[float, float]:
        """Effective footprint for candidate generation: pot, or crown reduced by the allowed overlap."""
        if orient.name != "upright":
            lx, ly, _ = item.bounding(orient)
            return lx, ly
        px, py = item.pot_footprint
        d = 2 * item.max_crown_radius() * (1 - item.overlap) * (1 - item.compress * 0.3)
        return max(px, d), max(py, d)

    def _grid(
        self, sp: Space, item: PlantItem, orient: Orientation, level: str, step: float = 10.0
    ) -> list[tuple[float, float]]:
        """Fallback candidates on a regular grid (also hits gaps between large crowns)."""
        rx, ry = item.pot_footprint if orient.name == "upright" else item.bounding(orient)[:2]
        if level == "floor":
            x_min, y_min, x_max, y_max = 0.0, 0.0, sp.length, sp.width
        else:
            sh = next(s for s in sp.shelves if s.id == level)
            x_min, y_min, x_max, y_max = sh.x0, sh.y0, sh.x0 + sh.length, sh.y0 + sh.depth

        def axis(lo: float, hi: float, size: float) -> list[float]:
            a, b = lo + size / 2, hi - size / 2
            if b < a - 0.01:
                return []
            n = max(1, int((b - a) // step))
            return [round(a + (b - a) * k / n, 1) for k in range(n + 1)]

        return [(cx, cy) for cx in axis(x_min, x_max, rx) for cy in axis(y_min, y_max, ry)]

    def _candidates(
        self, sp: Space, placed: list[Placement], item: PlantItem, orient: Orientation, level: str
    ) -> list[tuple[float, float]]:
        """Extreme points: per placed footprint the corners next to it (towards the door and to the
        side), aligned to the left and right wall; for the effective (crown) and rigid (pot) extent."""
        ex, ey = self._extent(item, orient)
        rx, ry = item.pot_footprint if orient.name == "upright" else (ex, ey)
        if level == "floor":
            x_min, y_min, x_max, y_max = 0.0, 0.0, sp.length, sp.width
            rects = [(ob.x0, ob.y0, ob.x1, ob.y1) for ob in sp.obstacles]
        else:
            sh = next(s for s in sp.shelves if s.id == level)
            x_min, y_min, x_max, y_max = sh.x0, sh.y0, sh.x0 + sh.length, sh.y0 + sh.depth
            rects = []
        for q in placed:
            if q.space_id == sp.id and q.level == level:
                qx, qy = self._extent(q.item, q.orientation)
                rects.append((q.x - qx / 2, q.y - qy / 2, q.x + qx / 2, q.y + qy / 2))
                rects.append(q.rigid_rect())
        corners: set[tuple[float, float]] = {(x_min, y_min), (x_min, y_max - ey), (x_min, y_max - ry)}
        c = self.s.clearance
        for x0, y0, x1, y1 in rects:
            corners |= {
                (x1 + c, y0),
                (x1 + c, y_min),
                (x1 + c, y_max - ey),
                (x1 + c, y_max - ry),  # behind it (towards the door)
                (x0, y1 + c),
                (x_min, y1 + c),
                (x0, y0 - ey - c),
                (x0, y0 - ry - c),  # beside it
                (x1 + c, y1 + c),
                (x1 + c, y0 - ey - c),
            }
        pts: set[tuple[float, float]] = set()
        if orient.name == "upright":
            # positions where the crowns (reduced by the allowed overlap) or the pots just touch
            for q in placed:
                if q.space_id != sp.id or q.level != level or q.orientation.name != "upright":
                    continue
                allowed = (item.overlap + q.item.overlap) / 2
                dist = (
                    max(
                        (item.max_crown_radius() + q.item.max_crown_radius()) * (1 - allowed),
                        item.pot_radius + q.item.pot_radius + self.s.clearance,
                    )
                    + 1.0
                )
                for k in range(16):
                    a = 2 * math.pi * k / 16
                    pts.add((round(q.x + dist * math.cos(a), 1), round(q.y + dist * math.sin(a), 1)))
            pts = {
                (cx, cy)
                for cx, cy in pts
                if x_min + rx / 2 - 0.01 <= cx <= x_max - rx / 2 + 0.01
                and y_min + ry / 2 - 0.01 <= cy <= y_max - ry / 2 + 0.01
            }
        for cx0, cy0 in corners:
            for wx, wy in ((ex, ey), (rx, ry)):
                cx, cy = cx0 + wx / 2, cy0 + wy / 2
                if cx - rx / 2 < x_min - 0.01 or cx + rx / 2 > x_max + 0.01:
                    continue
                if cy - ry / 2 < y_min - 0.01 or cy + ry / 2 > y_max + 0.01:
                    continue
                pts.add((round(cx, 1), round(cy, 1)))
        return sorted(pts)

    def place(
        self, sequence: list[tuple[PlantItem, Orientation]]
    ) -> tuple[list[Placement], list[dict[str, Any]]]:
        placed: list[Placement] = []
        unplaced: list[dict[str, Any]] = []
        loads = {sp.id: 0.0 for sp in self.spaces}
        shelf_loads: dict[str, float] = {}
        # Lane along the left wall kept free for plants that will be loaded lying (along x) later:
        # one strip per lying plant still to come, side by side next to the lying plants already
        # placed, at most 85 % of the width. Other plants use it only if nothing else fits.
        # A strip stays free over the whole length: the plant has to be slid in from the door.
        lying_after: list[list[tuple[float, float]]] = [[] for _ in range(len(sequence) + 1)]
        for i in range(len(sequence) - 1, -1, -1):
            it, o = sequence[i]
            strip = (
                [(it.bounding(o)[1] + self.s.clearance, it.bounding(o)[0] + self.s.clearance)]
                if o.name == "lying_x"
                else []
            )
            lying_after[i] = strip + lying_after[i + 1]
        # low obstacles at the left wall (wheel arch): (start x, width) - only long lying plants reach them
        arch = {
            sp.id: min(((ob.x0, ob.y1) for ob in sp.obstacles if ob.y0 <= 0.01), default=(sp.length, 0.0))
            for sp in self.spaces
        }
        for seq_no, (item, orient) in enumerate(sequence, start=1):
            to_come = lying_after[seq_no] if orient.name != "lying_x" else []
            reason = self.loadable(item)
            if reason:
                unplaced.append({"plant_id": item.plant_id, "number": item.number, "reason": reason})
                continue
            done = False
            for sp in self.spaces:
                if loads[sp.id] + item.weight > sp.payload:
                    continue
                lx, _ly, _h = item.bounding(orient)
                if orient.name == "upright":
                    lx = item.pot_footprint[0]
                levels = ["floor"]
                if orient.name == "upright":
                    levels = [
                        s.id for s in sp.shelves if item.total_h <= s.clearance and item.weight <= s.max_load
                    ] + levels
                best: Placement | None = None
                hint = self.hints.get(item.plant_id)
                if hint is not None and hint[0] == sp.id and hint[3] in levels:
                    # proposed position first - kept only if every rule holds
                    z = 0.0 if hint[3] == "floor" else next(s.z for s in sp.shelves if s.id == hint[3])
                    p = Placement(item, sp.id, orient, hint[1], hint[2], z, hint[3], seq_no)
                    if self._valid(p, sp, placed, shelf_loads):
                        best = p
                        self.hints_used += 1
                strips: list[tuple[float, float, float]] = []  # (y0, y1, length from the front wall)
                if to_come:
                    edge = max(
                        (
                            p.rigid_rect()[3]
                            for p in placed
                            if p.space_id == sp.id and p.level == "floor" and p.orientation.name == "lying_x"
                        ),
                        default=0.0,
                    )
                    arch_x, arch_w = arch[sp.id]
                    for w, length in to_come:
                        start = max(edge, arch_w) if length > arch_x else edge
                        if start + w > 0.85 * sp.width:
                            break
                        strips.append((start, start + w, sp.length))
                        edge = start + w
                # extreme points first, a coarse grid only if none of them is valid; keeping the lane free first
                for keep_lane, use_grid in ((True, False), (True, True), (False, False), (False, True)):
                    if best is not None:
                        break
                    if keep_lane and not strips:
                        continue
                    for level in levels:
                        z = 0.0 if level == "floor" else next(s.z for s in sp.shelves if s.id == level)
                        cands = (
                            self._grid(sp, item, orient, level)
                            if use_grid
                            else self._candidates(sp, placed, item, orient, level)
                        )
                        # deepest first (small x), then along the left wall: the first valid candidate wins
                        cands = sorted(cands, key=lambda c: (round(c[0] - lx / 2, 0), c[1]))
                        for cx, cy in cands:
                            p = Placement(item, sp.id, orient, cx, cy, z, level, seq_no)
                            if keep_lane and level == "floor":
                                rx0, ry0, _rx1, ry1 = p.rigid_rect()
                                if any(ry0 < sy1 and sy0 < ry1 and rx0 < sl for sy0, sy1, sl in strips):
                                    continue
                            if self._valid(p, sp, placed, shelf_loads):
                                best = p
                                break
                        if best is not None:
                            break
                    if best is not None:
                        break
                if best is not None:
                    placed.append(best)
                    loads[sp.id] += item.weight
                    if best.level != "floor":
                        shelf_loads[best.level] = shelf_loads.get(best.level, 0) + item.weight
                    done = True
                    break
            if not done:
                payload_full = all(loads[sp.id] + item.weight > sp.payload for sp in self.spaces)
                unplaced.append(
                    {
                        "plant_id": item.plant_id,
                        "number": item.number,
                        "reason": "payload" if payload_full else "space",
                    }
                )
        return placed, unplaced

    # ------------------------------------------------------------------ evaluation

    def evaluate(
        self, placed: list[Placement], unplaced: list[dict[str, Any]]
    ) -> tuple[float, dict[str, Any], list[str]]:
        violations: list[str] = []
        metrics: dict[str, Any] = {"spaces": {}}
        soft = 0.0
        hard = 0
        for sp in self.spaces:
            items = [p for p in placed if p.space_id == sp.id]
            if not items:
                continue
            w = sum(p.item.weight for p in items)
            cog_x = sum(p.item.weight * p.x for p in items) / w if w else 0
            cog_y = sum(p.item.weight * p.y for p in items) / w if w else 0
            lateral = abs(cog_y - sp.width / 2) / sp.width
            used = max(p.rigid_rect()[2] for p in items) / sp.length
            floor_area = sum(
                (r[2] - r[0]) * (r[3] - r[1]) for r in (p.rigid_rect() for p in items if p.level == "floor")
            )
            m: dict[str, Any] = {
                "weight": round(w, 1),
                "payload": sp.payload,
                "cog_x": round(cog_x, 1),
                "cog_y": round(cog_y, 1),
                "lateral_offset": round(lateral, 3),
                "used_length": round(used, 3),
                "floor_use": round(floor_area / (sp.length * sp.width), 3),
            }
            if lateral > self.s.cog_tolerance:
                violations.append(f"lateral_cog:{sp.id}")
                soft += 3
            if (
                sp.front_axle_x is not None
                and sp.rear_axle_x is not None
                and sp.rear_axle_x > sp.front_axle_x
            ):
                rear = sum(p.item.weight * (p.x - sp.front_axle_x) for p in items) / (
                    sp.rear_axle_x - sp.front_axle_x
                )
                front = w - rear
                m["axle_front"], m["axle_rear"] = round(front, 1), round(rear, 1)
                if sp.max_front_extra and front > sp.max_front_extra:
                    violations.append(f"axle_front:{sp.id}")
                    hard += 1
                if sp.max_rear_extra and rear > sp.max_rear_extra:
                    violations.append(f"axle_rear:{sp.id}")
                    hard += 1
            elif sp.hitch_x is not None and sp.rear_axle_x is not None:
                tongue = sum(p.item.weight * (sp.rear_axle_x - p.x) for p in items) / (
                    sp.rear_axle_x - sp.hitch_x
                )
                m["tongue_load"] = round(tongue, 1)
                if sp.max_tongue is not None and tongue > sp.max_tongue:
                    violations.append(f"tongue_high:{sp.id}")
                    hard += 1
                if sp.min_tongue is not None and tongue < sp.min_tongue:
                    violations.append(f"tongue_low:{sp.id}")
                    hard += 1
            for p in items:
                rx0, ry0, rx1, ry1 = p.rigid_rect()
                for q in items:
                    if q is p or q.level != p.level:
                        continue
                    qx0, qy0, qx1, qy1 = q.rigid_rect()
                    same_lane = ry0 < qy1 and qy0 < ry1
                    if not same_lane:
                        continue
                    # sensitive plant with a heavy pot directly behind it (towards the door)
                    if (
                        p.item.sensitive
                        and q.item.weight >= self.s.heavy_kg
                        and qx0 >= rx1 - 1
                        and qx0 - rx1 < 40
                    ):
                        violations.append(f"sensitive_behind_heavy:{p.item.number}")
                        soft += 2
                    # a plant of a later stop (loaded later) deeper than one of an earlier stop in the same lane
                    later = (
                        q.item.stop_position > p.item.stop_position
                        if self.s.direction == "pickup"
                        else q.item.stop_position < p.item.stop_position
                    )
                    if later and qx1 <= rx0 + 1:
                        soft += 1.5
                        if f"order_blocked:{q.item.number}" not in violations:
                            violations.append(f"order_blocked:{q.item.number}")
                if (
                    p.orientation.name != "upright"
                    and p.item.total_h <= sp.height
                    and p.item.total_h <= sp.door_h + 15
                ):
                    soft += 2  # lying only if it helps: more handling, more risk for the crown
                if p.orientation.name == "upright" and p.level == "floor":
                    base = min(p.item.pot_footprint)
                    if base > 0 and p.item.total_h / base > self.s.tall_ratio:
                        at_wall = ry0 < 15 or ry1 > sp.width - 15 or rx0 < 15
                        if not at_wall:
                            soft += 0.5
            metrics["spaces"][sp.id] = m
        n_un = len(unplaced)
        used_total = sum(m.get("used_length", 0) for m in metrics["spaces"].values())
        score = n_un * 1e6 + hard * 1e4 + soft * 30 + used_total * 50
        metrics["placed"] = len(placed)
        metrics["unplaced"] = n_un
        return score, metrics, violations

    # ------------------------------------------------------------------ search

    def options(self, item: PlantItem) -> list[Orientation]:
        """Orientations that fit at least one cargo space (height and length)."""
        out = []
        for o in item.orientations(0):
            lx, ly, h = item.bounding(o)
            if any(h <= sp.height and lx <= sp.length and ly <= sp.width for sp in self.spaces):
                out.append(o)
        return out or item.orientations(0)[:1]

    def initial_sequence(self, items: list[PlantItem]) -> list[tuple[PlantItem, Orientation]]:
        key_size = {
            "size": lambda it: (-it.pot_radius * it.total_h,),
            "weight": lambda it: (-it.weight,),
            "tour": lambda it: (0,),
            "tour_then_size": lambda it: (-(it.pot_radius**2) * it.weight,),
        }.get(self.s.sort_rule, lambda it: (-it.weight,))
        if self.s.sort_rule in ("tour", "tour_then_size"):
            order = sorted(items, key=lambda it: (self._group(it), *key_size(it)))
        else:
            order = sorted(items, key=lambda it: key_size(it))
        out = []
        for it in order:
            # stand upright if possible, otherwise start lying
            out.append((it, self.options(it)[0]))
        if self.s.sort_rule in ("tour", "tour_then_size"):
            # per stop: lying plants first (shortest first: they fit in front of the wheel arch), then upright
            out.sort(
                key=lambda pair: (
                    self._group(pair[0]),
                    0 if pair[1].name != "upright" else 1,
                    pair[0].total_h if pair[1].name != "upright" else 0,
                )
            )
        return out

    def _group(self, it: PlantItem) -> int:
        return it.stop_position if self.s.direction == "pickup" else -it.stop_position

    def start_sequence(
        self, items: list[PlantItem], layout: StartLayout
    ) -> list[tuple[PlantItem, Orientation]]:
        """Loading order and orientations of a proposed layout; plants it misses follow in rule order."""
        by_id = {it.plant_id: it for it in items}
        rule = self.initial_sequence(items)
        seq: list[tuple[PlantItem, Orientation]] = []
        for pid in layout.sequence:
            it = by_id.pop(pid, None)
            if it is None:
                continue
            options = self.options(it)
            want = layout.orientation.get(pid)
            seq.append((it, next((o for o in options if o.name == want), options[0])))
        seq += [(it, o) for it, o in rule if it.plant_id in by_id]
        # the loading order of the stops is a hard rule: the proposal's order counts within a stop
        seq.sort(key=lambda pair: self._group(pair[0]))
        return seq

    def run(self, items: list[PlantItem], start_layout: StartLayout | None = None) -> PackResult:
        start = time.monotonic()
        by_id = {it.plant_id: it for it in items}
        static = [
            {"plant_id": it.plant_id, "number": it.number, "reason": r}
            for it in items
            if (r := self.loadable(it))
        ]
        skip = {u["plant_id"] for u in static}
        items = [it for it in items if it.plant_id not in skip]
        if start_layout is not None:
            self.hints = dict(start_layout.positions)
            seq = self.start_sequence(items, start_layout)
        else:
            seq = self.initial_sequence(items)
        self.hints_used = 0
        placed, unplaced = self.place(seq)
        best_score, best_metrics, best_viol = self.evaluate(placed, unplaced)
        start_info = (
            {
                "source": start_layout.source,
                "score": round(best_score, 1),
                "unplaced": len(unplaced),
                "positions_proposed": len(start_layout.positions),
                "positions_valid": self.hints_used,
            }
            if start_layout is not None
            else None
        )
        best = (list(seq), placed, unplaced)
        cur_seq, cur_score = list(seq), best_score
        # the proposed positions only shape the start solution; the annealing then searches freely
        # and keeps the start only while nothing better (fewer violations, better balance) is found
        self.hints = {}
        iterations = 0
        limit = self.s.time_limit_s
        if not unplaced and best_score < 1e4:
            limit = min(limit, 0.3 + 0.02 * len(items))  # already valid: polish only briefly
        if len(items) > 1 or any(it.can_tilt for it in items):
            t0, t1 = 50.0, 0.5
            while time.monotonic() - start < limit and best_score > 0:
                iterations += 1
                frac = (time.monotonic() - start) / limit
                temp = t0 * (t1 / t0) ** frac
                cand = self._neighbour(cur_seq)
                if cand is None:
                    break
                p2, u2 = self.place(cand)
                sc, mt, vi = self.evaluate(p2, u2)
                if sc < cur_score or self.rng.random() < math.exp(-(sc - cur_score) / max(temp, 1e-6)):
                    cur_seq, cur_score = cand, sc
                    if sc < best_score:
                        best_score, best_metrics, best_viol = sc, mt, vi
                        best = (list(cand), p2, u2)
                if best_score < 1e4 and not best[2] and limit == self.s.time_limit_s:
                    limit = min(limit, time.monotonic() - start + 0.3)
        seq, placed, unplaced = best
        unplaced = static + unplaced
        hard_viol = [
            v
            for v in best_viol
            if v.split(":")[0] in ("axle_front", "axle_rear", "tongue_high", "tongue_low")
        ]
        ok = not unplaced and not hard_viol
        message = pack_message(ok, unplaced, hard_viol, by_id)
        best_metrics["seconds"] = round(time.monotonic() - start, 2)
        if start_info is not None:
            best_metrics["start"] = start_info
        result = PackResult(
            ok, placed, unplaced, best_metrics, sorted(set(best_viol)), message, iterations, best_score
        )
        result.instructions = {
            p.item.plant_id: instruction(p, self.space_by_id(p.space_id), self.s.tall_ratio) for p in placed
        }
        return result

    def space_by_id(self, sid: str) -> Space:
        return next(s for s in self.spaces if s.id == sid)

    def _neighbour(
        self, seq: list[tuple[PlantItem, Orientation]]
    ) -> list[tuple[PlantItem, Orientation]] | None:
        n = len(seq)
        cand = list(seq)
        for _ in range(20):
            move = self.rng.random()
            if move < 0.45 and n > 1:
                i = self.rng.randrange(n)
                same = [j for j in range(n) if j != i and self._group(cand[j][0]) == self._group(cand[i][0])]
                if same:
                    j = self.rng.choice(same)
                    cand[i], cand[j] = cand[j], cand[i]
                    return cand
            elif move < 0.75:
                tiltable = [i for i in range(n) if len(self.options(cand[i][0])) > 1]
                if tiltable:
                    i = self.rng.choice(tiltable)
                    options = self.options(cand[i][0])
                    cur = next((k for k, o in enumerate(options) if o.name == cand[i][1].name), 0)
                    cand[i] = (
                        cand[i][0],
                        options[(cur + 1 + self.rng.randrange(len(options) - 1)) % len(options)],
                    )
                    return cand
            elif n > 2:
                i = self.rng.randrange(n)
                group = self._group(cand[i][0])
                idx = [j for j in range(n) if self._group(cand[j][0]) == group]
                if len(idx) > 1:
                    item = cand.pop(i)
                    idx = [j for j in range(len(cand)) if self._group(cand[j][0]) == group] or [i]
                    cand.insert(self.rng.choice(idx + [idx[-1] + 1]), item)
                    return cand
        return None


def instruction(p: Placement, sp: Space, tall_ratio: float = 3.0) -> dict[str, Any]:
    """Loading instruction from the loader's view at the door (looking in); texts in the i18n file."""
    x0, y0, x1, y1 = p.rigid_rect()
    depth = (p.x) / sp.length
    if depth < 0.34:
        where_x = t("packing.instr.front_wall") if x0 < 20 else t("packing.instr.back")
    elif depth < 0.67:
        where_x = t("packing.instr.middle")
    else:
        where_x = t("packing.instr.door")
    side = "left" if y0 < 20 else "right" if y1 > sp.width - 20 else "center"
    if p.level == "floor":
        level = t("packing.instr.floor")
    else:
        level = t("packing.instr.shelf", name=next(s.name for s in sp.shelves if s.id == p.level))
    parts = [f"{where_x} {t('packing.instr.' + side)} {level}"]
    secure = p.item.must_secure
    if p.orientation.name == "upright":
        if side != "center":
            parts.append(t("packing.instr.crown_to_wall"))
        base = min(p.item.pot_footprint)
        if (base > 0 and p.item.total_h / base > tall_ratio) or p.item.tip_tendency > 0.6:
            secure = True
    elif p.orientation.name == "lying_x":
        parts.append(t("packing.instr.lying_x"))
    elif p.orientation.name == "lying_y":
        parts.append(
            t(
                "packing.instr.lying_y",
                side=t("packing.instr.left" if p.y < sp.width / 2 else "packing.instr.right"),
            )
        )
    else:
        parts.append(t("packing.instr.tilted", angle=int(p.orientation.angle)))
    if p.item.sensitive:
        parts.append(t("packing.instr.sensitive"))
    if secure:
        parts.append(t("packing.instr.secure"))
    return {"text": ", ".join(parts), "secure": secure, "space": sp.name}

"""Geometry of cargo spaces and plants for the load planner (units: cm, kg).

Coordinates of a cargo space: x from the front wall (cab side, deepest point) to the door,
y from the left wall to the right wall, z up from the floor.

A plant has a rigid part (pot: cylinder or box, never overlaps anything) and a soft crown
(cylinder, cone, sphere, column or free form) that may overlap neighbouring crowns by an allowed
fraction (from density, compressibility and the setting packing.crown_overlap). Nothing is
stacked on plants; plants stand on the floor or on a shelf.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    z1: float  # height of the obstacle

    def overlaps(self, x0: float, y0: float, x1: float, y1: float, eps: float = 0.5) -> bool:
        """True if the rectangle overlaps this obstacle by more than eps (rounding tolerance)."""
        return x0 < self.x1 - eps and self.x0 < x1 - eps and y0 < self.y1 - eps and self.y0 < y1 - eps


@dataclass
class Shelf:
    id: str
    name: str
    x0: float
    y0: float
    length: float
    depth: float
    z: float  # height of the shelf surface
    clearance: float
    max_load: float
    blocks_floor: bool


@dataclass
class Space:
    """One cargo space (vehicle or trailer)."""

    id: str
    name: str
    kind: str
    length: float
    width: float
    height: float
    door_w: float
    door_h: float
    payload: float
    obstacles: list[Box] = field(default_factory=list)
    shelves: list[Shelf] = field(default_factory=list)
    front_axle_x: float | None = None
    rear_axle_x: float | None = None
    max_front_extra: float | None = None
    max_rear_extra: float | None = None
    hitch_x: float | None = None
    max_tongue: float | None = None
    min_tongue: float | None = None


@dataclass
class Orientation:
    name: str  # upright | lying_x | lying_y | tilted_x
    angle: float  # tilt in degrees (0 = upright)


@dataclass
class PlantItem:
    plant_id: str
    number: int
    order_id: str
    stop_position: int
    label: str
    weight: float
    pot_shape: str  # round | square
    pot_d: float
    pot_l: float
    pot_w: float
    pot_h: float
    crown_shape: str
    crown_w: float
    crown_h: float
    crown_start: float  # above the pot rim
    total_h: float
    overlap: float  # allowed crown overlap fraction
    compress: float
    can_tilt: bool
    tilt_max_deg: float
    sensitive: bool
    must_secure: bool
    tip_tendency: float

    @property
    def pot_radius(self) -> float:
        return self.pot_d / 2 if self.pot_shape == "round" else max(self.pot_l, self.pot_w) / 2

    @property
    def pot_footprint(self) -> tuple[float, float]:
        return (self.pot_d, self.pot_d) if self.pot_shape == "round" else (self.pot_l, self.pot_w)

    def crown_radius_at(self, z: float) -> float:
        """Radius of the crown hull at height z above the floor (upright)."""
        z0 = self.pot_h + self.crown_start
        z1 = z0 + self.crown_h
        if z < z0 or z > z1 or self.crown_h <= 0:
            return 0.0
        r = self.crown_w / 2
        t = (z - z0) / self.crown_h
        if self.crown_shape == "cone":
            return r * (1 - t)
        if self.crown_shape == "sphere":
            return r * math.sqrt(max(0.0, 1 - (2 * t - 1) ** 2))
        if self.crown_shape == "column":
            return r * 0.85
        if self.crown_shape == "free":
            return r * (0.7 + 0.3 * math.sin(math.pi * t))
        return r

    def max_crown_radius(self) -> float:
        z0 = self.pot_h + self.crown_start
        return max((self.crown_radius_at(z0 + self.crown_h * k / 10) for k in range(11)), default=0.0)

    def passage_width(self) -> float:
        return max(self.pot_radius * 2, self.crown_w * (1 - self.compress))

    def orientations(self, space_height: float) -> list[Orientation]:
        out = [Orientation("upright", 0)]
        if self.can_tilt and self.tilt_max_deg >= 60:
            out += [Orientation("lying_x", 90), Orientation("lying_y", 90)]
        elif self.can_tilt and self.tilt_max_deg >= 15:
            out.append(Orientation("tilted_x", self.tilt_max_deg))
        return out

    def bounding(self, o: Orientation) -> tuple[float, float, float]:
        """(length along x, width along y, height) of the bounding box in an orientation."""
        width = max(self.pot_radius * 2, self.crown_w * (1 - self.compress * 0.5))
        if o.name == "upright":
            return self.pot_footprint[0], self.pot_footprint[1], self.total_h
        if o.name == "lying_x":
            return self.total_h, width, width
        if o.name == "lying_y":
            return width, self.total_h, width
        a = math.radians(o.angle)
        length = self.total_h * math.sin(a) + width * math.cos(a)
        height = self.total_h * math.cos(a) + width * math.sin(a)
        return length, width, height


@dataclass
class Placement:
    item: PlantItem
    space_id: str
    orientation: Orientation
    x: float  # centre of the pot footprint (upright) or of the bounding box (lying)
    y: float
    z: float  # floor or shelf height
    level: str  # floor | shelf id
    seq: int = 0

    def rigid_rect(self) -> tuple[float, float, float, float]:
        """Rigid footprint as rectangle (x0, y0, x1, y1)."""
        it = self.item
        if self.orientation.name == "upright":
            lx, ly = it.pot_footprint
        else:
            lx, ly, _ = it.bounding(self.orientation)
        return self.x - lx / 2, self.y - ly / 2, self.x + lx / 2, self.y + ly / 2

    def pot_rect(self) -> tuple[float, float, float, float]:
        """Rectangle of the pot only. Lying plants: pot towards the front wall (lying_x) or the
        left wall (lying_y); the crown part may rest over low obstacles such as wheel arches."""
        x0, y0, x1, y1 = self.rigid_rect()
        it = self.item
        if self.orientation.name in ("lying_x", "tilted_x"):
            return x0, self.y - it.pot_radius, x0 + it.pot_h, self.y + it.pot_radius
        if self.orientation.name == "lying_y":
            return self.x - it.pot_radius, y0, self.x + it.pot_radius, y0 + it.pot_h
        return x0, y0, x1, y1

    def top(self) -> float:
        return self.z + self.item.bounding(self.orientation)[2]


def rigid_conflict(a: Placement, b: Placement, clearance: float) -> bool:
    """Pots (and lying plants) never overlap. Circles for round pots, rectangles otherwise."""
    if a.level != b.level:
        return False
    eps = 0.5  # rounding tolerance of candidate positions
    if (
        a.orientation.name == "upright"
        and b.orientation.name == "upright"
        and a.item.pot_shape == "round"
        and b.item.pot_shape == "round"
    ):
        d = math.hypot(a.x - b.x, a.y - b.y)
        return d < a.item.pot_radius + b.item.pot_radius + clearance - eps
    ax0, ay0, ax1, ay1 = a.rigid_rect()
    bx0, by0, bx1, by1 = b.rigid_rect()
    c = clearance - eps
    return ax0 < bx1 + c and bx0 < ax1 + c and ay0 < by1 + c and by0 < ay1 + c


def crown_conflict(a: Placement, b: Placement) -> bool:
    """Crowns of upright plants may overlap by the allowed fraction; a crown may overhang a
    neighbouring pot only above that pot's rim."""
    if a.orientation.name != "upright" or b.orientation.name != "upright" or a.level != b.level:
        return False
    d = math.hypot(a.x - b.x, a.y - b.y)
    ia, ib = a.item, b.item
    allowed = (ia.overlap + ib.overlap) / 2
    # crown vs crown at the same heights
    za0, za1 = a.z + ia.pot_h + ia.crown_start, a.z + ia.pot_h + ia.crown_start + ia.crown_h
    zb0, zb1 = b.z + ib.pot_h + ib.crown_start, b.z + ib.pot_h + ib.crown_start + ib.crown_h
    lo, hi = max(za0, zb0), min(za1, zb1)
    if hi > lo:
        for k in range(6):
            z = lo + (hi - lo) * k / 5
            ra = ia.crown_radius_at(z - a.z)
            rb = ib.crown_radius_at(z - b.z)
            if ra > 0 and rb > 0 and d < (ra + rb) * (1 - allowed):
                return True
    # crown of a over the pot of b: allowed only above b's pot rim
    for p, q in ((a, b), (b, a)):
        rim = q.z + q.item.pot_h
        z_crown_bottom = p.z + p.item.pot_h + p.item.crown_start
        if z_crown_bottom < rim:
            r = p.item.crown_radius_at(rim - p.z)
            if r > 0 and d < r * (1 - p.item.compress * 0.5) + q.item.pot_radius:
                return True
    return False


def crown_inside_walls(p: Placement, space: Space) -> bool:
    if p.orientation.name != "upright":
        return True
    r = p.item.max_crown_radius() * (1 - p.item.compress * 0.6)
    return p.x - r >= -1 and p.x + r <= space.length + 1 and p.y - r >= -1 and p.y + r <= space.width + 1

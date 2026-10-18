"""Planning input: stops (orders) and units (one vehicle + team on one day).

Team formation (setting planning.form_teams):
  fixed – only active fixed teams valid that day (weekdays, period) whose members and vehicle are
          available; a team that cannot work becomes a team issue with its reason (no error)
  auto  – fixed teams first, then teams formed from the remaining staff per day: one large team
          for heavy stops if needed, the rest with the default size; every team gets a driver with
          the required licence (incl. BE/C1E for a trailer).
Scenarios modify the resources before units are formed (extra/removed staff, vehicles, days).
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fleet.layout import vehicle_layout
from app.models.masterdata import LICENCE_INCLUDES, Equipment, StaffMember, Team, Vehicle
from app.models.orders import Address, Customer, PickupOrder, Plant
from app.planning.availability import day_windows
from app.settings.service import SettingsResolver
from app.timemodel.estimate import Estimator, PlantCalc, equipment_info
from app.timemodel.plantfill import footprint_m2, geometry, volume_m3
from app.timemodel.teams import EquipmentInfo


def minutes(t: time | None, default: int) -> int:
    return default if t is None else t.hour * 60 + t.minute


def hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


@dataclass
class Member:
    id: str
    name: str
    licences: set[str]
    solo_kg: float
    carry_factor: float
    carry_speed: float
    drive_speed: float
    hourly_cost: float
    max_work_min: int
    start: int
    end: int
    virtual: bool = False

    def can_drive(self, required: str) -> bool:
        return any(required in LICENCE_INCLUDES.get(lic, {lic}) for lic in self.licences)


@dataclass
class VehicleIn:
    id: str
    name: str
    kind: str
    licence: str
    length: float
    width: float
    height: float
    door_w: float
    door_h: float
    payload: float
    area_m2: float
    volume_m3: float
    seats: int
    can_tow: bool
    default_trailer: str | None
    per_km: float
    per_hour: float
    speed_factor: float
    trailer_speed_factor: float
    unload_min: float
    max_trips: int
    start: int
    end: int
    equipment: list[EquipmentInfo] = field(default_factory=list)
    virtual: bool = False


@dataclass
class Unit:
    key: str
    date: date
    day_index: int
    vehicle: VehicleIn
    trailer: VehicleIn | None
    members: list[Member]
    driver: Member
    start: int
    end: int  # regular end (overtime beyond)
    hard_end: int
    break_min: int
    unload_min: float
    max_trips: int
    cap_weight: float
    cap_area: float
    cap_volume: float
    fixed_team_id: str | None = None

    @property
    def team_size(self) -> int:
        return len(self.members)

    @property
    def carry_speed(self) -> float:
        return sum(m.carry_speed for m in self.members) / max(1, len(self.members))

    @property
    def drive_factor(self) -> float:
        f = self.vehicle.speed_factor * self.driver.drive_speed
        if self.trailer is not None:
            f *= self.trailer.trailer_speed_factor
        return max(0.2, f)

    @property
    def labour_cost_min(self) -> float:
        return sum(m.hourly_cost for m in self.members) / 60

    @property
    def vehicle_cost_min(self) -> float:
        return (self.vehicle.per_hour + (self.trailer.per_hour if self.trailer else 0)) / 60

    @property
    def cost_km(self) -> float:
        return self.vehicle.per_km + (self.trailer.per_km if self.trailer else 0)

    @property
    def equipment(self) -> list[EquipmentInfo]:
        return self.vehicle.equipment + (self.trailer.equipment if self.trailer else [])

    def profile_key(self, shared_equipment: list[EquipmentInfo]) -> tuple:
        return (
            self.team_size,
            round(self.carry_speed, 3),
            tuple(sorted(m.solo_kg for m in self.members)),
            round(self.members[0].carry_factor, 3) if self.members else 0,
            tuple(sorted(e.id for e in self.equipment + shared_equipment)),
        )

    def label(self) -> str:
        v = self.vehicle.name + (f" + {self.trailer.name}" if self.trailer else "")
        return f"{v} · {', '.join(m.name.split()[0] for m in self.members)}"

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "date": self.date.isoformat(),
            "vehicle_id": self.vehicle.id,
            "vehicle": self.vehicle.name,
            "trailer_id": self.trailer.id if self.trailer else None,
            "trailer": self.trailer.name if self.trailer else None,
            "members": [{"id": m.id, "name": m.name, "virtual": m.virtual} for m in self.members],
            "driver_id": self.driver.id,
            "start": self.start,
            "end": self.end,
            "hard_end": self.hard_end,
            "break_min": self.break_min,
            "team_size": self.team_size,
            "carry_speed": round(self.carry_speed, 3),
            "drive_factor": round(self.drive_factor, 3),
            "cap_weight": self.cap_weight,
            "cap_area": round(self.cap_area, 2),
            "cap_volume": round(self.cap_volume, 2),
            "labour_cost_min": round(self.labour_cost_min, 4),
            "vehicle_cost_min": round(self.vehicle_cost_min, 4),
            "cost_km": round(self.cost_km, 4),
            "unload_min": self.unload_min,
            "max_trips": self.max_trips,
            "fixed_team_id": self.fixed_team_id,
            "virtual": self.vehicle.virtual or any(m.virtual for m in self.members),
        }


@dataclass
class StopIn:
    order: PickupOrder
    number: str
    customer: str
    lat: float | None
    lon: float | None
    plants: list[Plant]
    calcs: list[PlantCalc]
    weight: float
    area: float
    volume: float
    min_team: int
    dates: set[date] | None
    windows: list[tuple[int, int, date | None]]
    price_net: float
    priority: int
    pinned_unit: str | None = None
    experiment: bool = False
    incompatible: set[str] = field(default_factory=set)
    paths: dict[Any, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return str(self.order.id)

    @property
    def crew(self) -> int:
        return max((c.crew.crew for c in self.calcs), default=1)


@dataclass
class PlanningInput:
    tenant_id: uuid.UUID
    depot: tuple[float, float]
    dates: list[date]
    units: list[Unit]
    stops: list[StopIn]
    unplannable: list[dict[str, Any]]
    estimator: Estimator
    shared_equipment: list[EquipmentInfo]
    settings: dict[str, Any]
    direction: str = "pickup"
    team_mode: str = "auto"
    # fixed teams that could not work on a day: {date, team_id, team, reason, names}
    team_issues: list[dict[str, Any]] = field(default_factory=list)
    # all fixed teams with their members (for hints on unassigned stops)
    fixed_teams: list[dict[str, Any]] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)  # staff, vehicle and team names by id
    staff_ids: list[str] = field(default_factory=list)  # active staff (not virtual)
    vehicles: list[VehicleIn] = field(default_factory=list)  # all active vehicles (not trailers)


# ----------------------------------------------------------------------------------- resources


def load_members(db: Session, r: SettingsResolver, tenant_id: uuid.UUID) -> list[tuple[StaffMember, Member]]:
    staff = list(
        db.scalars(
            select(StaffMember)
            .where(
                StaffMember.tenant_id == tenant_id,
                StaffMember.deleted_at.is_(None),
                StaffMember.active.is_(True),
            )
            .order_by(StaffMember.name)
        )
    )
    r.prefetch("staff", [s.id for s in staff])
    out = []
    for s in staff:
        ch = ("staff", s.id)
        wage = float(r.get("staff.hourly_wage", ch)) * (
            1 + float(r.get("staff.employer_share_pct", ch)) / 100
        )
        out.append(
            (
                s,
                Member(
                    id=str(s.id),
                    name=s.name,
                    licences=set(s.licences or []),
                    solo_kg=float(r.get("staff.solo_carry_kg", ch)),
                    carry_factor=float(r.get("staff.team_carry_factor", ch)),
                    carry_speed=float(r.get("staff.carry_speed_factor", ch)),
                    drive_speed=float(r.get("staff.drive_speed_factor", ch)),
                    hourly_cost=wage,
                    max_work_min=int(float(r.get("staff.max_work_hours_day", ch)) * 60),
                    start=0,
                    end=0,
                ),
            )
        )
    return out


def vehicle_in(
    db: Session, r: SettingsResolver, v: Vehicle, shared: list[EquipmentInfo], all_eq: list[Equipment]
) -> VehicleIn:
    ch = ("vehicle", v.id)
    arch = 0.0
    if v.wheel_arch_length_cm and v.wheel_arch_width_cm:
        arch = 2 * v.wheel_arch_length_cm * v.wheel_arch_width_cm
    layout = vehicle_layout(db, v.id)  # own shelves plus assigned modules (package C)
    area = (
        v.cargo_length_cm * v.cargo_width_cm - arch - layout.floor_blocked_cm2() + layout.shelf_area_cm2()
    ) / 10000
    per_km = float(r.get("costs.vehicle_per_km", ch)) + float(
        r.get("costs.fuel_l_per_100km", ch)
    ) / 100 * float(r.get("costs.fuel_price"))
    return VehicleIn(
        id=str(v.id),
        name=v.name,
        kind=v.kind,
        licence=v.required_licence or "B",
        length=v.cargo_length_cm,
        width=v.cargo_width_cm,
        height=v.cargo_height_cm,
        door_w=v.door_width_cm,
        door_h=v.door_height_cm,
        payload=max(0.0, v.payload_kg - layout.module_weight),
        area_m2=max(0.1, area),
        volume_m3=v.cargo_length_cm * v.cargo_width_cm * v.cargo_height_cm / 1e6,
        seats=v.seats or 2,
        can_tow=bool(v.can_tow),
        default_trailer=str(v.default_trailer_id) if v.default_trailer_id else None,
        per_km=per_km,
        per_hour=float(r.get("costs.vehicle_per_hour", ch)),
        speed_factor=float(r.get("drive.vehicle_speed_factor", ch)),
        trailer_speed_factor=float(r.get("drive.trailer_speed_factor", ch)),
        unload_min=float(r.get("planning.unload_min", ch)),
        max_trips=int(r.get("planning.max_trips_per_day", ch)),
        start=0,
        end=0,
        equipment=[equipment_info(e, r) for e in all_eq if e.vehicle_id == v.id and (e.count or 0) > 0],
    )


def break_minutes(r: SettingsResolver, work_min: int) -> int:
    if work_min > 9 * 60:
        return int(r.get("planning.break_after_9h_min"))
    if work_min > 6 * 60:
        return int(r.get("planning.break_after_6h_min"))
    return 0


def _demand_profile(stops: list[StopIn], day: date, max_size: int) -> int:
    crews = [s.crew for s in stops if s.dates is None or day in s.dates]
    return min(max(crews, default=2), max_size)


def form_units(
    r: SettingsResolver,
    day: date,
    day_index: int,
    members: list[Member],
    vehicles: list[VehicleIn],
    trailers: dict[str, VehicleIn],
    fixed_teams: list[tuple[str, list[str], str | None]],
    stops: list[StopIn],
    mode: str,
    default_size: int,
    team_size_override: int | None = None,
    issues: list[dict[str, Any]] | None = None,
    names: dict[str, str] | None = None,
) -> list[Unit]:
    """issues collects fixed teams that cannot work today (with reason); names: staff/vehicle names."""
    max_size = int(r.get("team.max_size"))
    pool = {m.id: m for m in members}
    free_vehicles = {v.id: v for v in vehicles}
    free_trailers = dict(trailers)
    units: list[Unit] = []
    names = names or {}
    used_by: dict[str, str] = {}  # staff or vehicle id -> fixed team that took it today
    last_reason: list[str] = []

    def make(vehicle: VehicleIn, team: list[Member], fixed_id: str | None) -> Unit | None:
        last_reason.clear()
        trailer = None
        need = vehicle.licence
        if vehicle.default_trailer and vehicle.default_trailer in free_trailers:
            t = free_trailers[vehicle.default_trailer]
            tow_lic = {"B": "BE", "C1": "C1E", "C": "CE"}.get(vehicle.licence, "BE")
            if any(m.can_drive(tow_lic) for m in team):
                trailer, need = t, tow_lic
        drivers = sorted((m for m in team if m.can_drive(need)), key=lambda m: len(m.licences))
        if not drivers:
            trailer, need = None, vehicle.licence
            drivers = sorted((m for m in team if m.can_drive(need)), key=lambda m: len(m.licences))
            if not drivers:
                last_reason.append("no_driver")
                return None
        driver = drivers[0]
        start = max([vehicle.start] + [m.start for m in team] + ([trailer.start] if trailer else []))
        end = min([vehicle.end] + [m.end for m in team] + ([trailer.end] if trailer else []))
        if end - start < 60:
            last_reason.append("short_day")
            return None
        brk = break_minutes(r, end - start)
        max_work = min(m.max_work_min for m in team)
        hard_end = start + max_work + brk
        if trailer is not None:
            free_trailers.pop(trailer.id, None)
        return Unit(
            key=f"{day.isoformat()}|{vehicle.id}|{hashlib.sha1('+'.join(sorted(m.id for m in team)).encode()).hexdigest()[:12]}",
            date=day,
            day_index=day_index,
            vehicle=vehicle,
            trailer=trailer,
            members=team,
            driver=driver,
            start=start,
            end=end,
            hard_end=max(end, hard_end),
            break_min=brk,
            unload_min=vehicle.unload_min,
            max_trips=vehicle.max_trips,
            cap_weight=vehicle.payload + (trailer.payload if trailer else 0),
            cap_area=vehicle.area_m2 + (trailer.area_m2 if trailer else 0),
            cap_volume=vehicle.volume_m3 + (trailer.volume_m3 if trailer else 0),
            fixed_team_id=fixed_id,
        )

    def issue(team_id: str, reason: str, ids: list[str] | None = None) -> None:
        if issues is None or team_id.startswith("forced:"):
            return
        issues.append(
            {
                "date": day.isoformat(),
                "team_id": team_id,
                "team": names.get(team_id, ""),
                "reason": reason,
                "names": [names.get(i, "?") for i in ids or []],
                "other_team": next((used_by[i] for i in ids or [] if i in used_by), None),
            }
        )

    for team_id, member_ids, vehicle_id in fixed_teams:
        team = [pool[i] for i in member_ids if i in pool]
        if not member_ids:
            issue(team_id, "no_members")
            continue
        if len(team) != len(member_ids):
            missing = [i for i in member_ids if i not in pool]
            busy = [i for i in missing if i in used_by]
            issue(team_id, "member_in_other_team" if busy else "member_absent", busy or missing)
            continue
        vehicle = free_vehicles.get(vehicle_id) if vehicle_id else None
        if vehicle is None:
            # the standard vehicle is a default: another free vehicle the team can drive takes over
            vehicle = next(
                (v for v in free_vehicles.values() if any(m.can_drive(v.licence) for m in team)), None
            )
            if vehicle_id and vehicle is not None:
                issue(team_id, "vehicle_replaced", [vehicle.id])
        if vehicle is None:
            if vehicle_id:
                reason = "vehicle_in_other_team" if vehicle_id in used_by else "vehicle_unavailable"
                issue(team_id, reason, [vehicle_id])
            else:
                issue(team_id, "no_vehicle")
            continue
        unit = make(vehicle, team, team_id)
        if unit is not None:
            units.append(unit)
            free_vehicles.pop(vehicle.id, None)
            used_by[vehicle.id] = names.get(team_id, "")
            for m in team:
                pool.pop(m.id, None)
                used_by[m.id] = names.get(team_id, "")
        else:
            issue(team_id, last_reason[0] if last_reason else "no_driver", [vehicle.id])
    if mode == "fixed":
        return units

    staff = sorted(pool.values(), key=lambda m: -m.solo_kg)
    vehs = sorted(free_vehicles.values(), key=lambda v: (-v.payload, v.name))
    size = max(1, team_size_override or default_size)
    n_units = min(len(vehs), len(staff) // size)
    if n_units == 0 and staff and vehs:
        n_units, size = 1, len(staff)
    sizes = [size] * n_units
    big = _demand_profile(stops, day, max_size) if team_size_override is None else size
    if n_units and big > size and len(staff) >= big:
        sizes[0] = big
        while sum(sizes) > len(staff) and len(sizes) > 1:
            sizes.pop()
    leftover = len(staff) - sum(sizes)
    i = 0
    while leftover > 0 and sizes:
        if sizes[i % len(sizes)] < max_size:
            sizes[i % len(sizes)] += 1
            leftover -= 1
        i += 1
        if i > 100:
            break
    # biggest team first; each team takes the largest free vehicle that has enough seats and a driver
    remaining = list(staff)
    used_vehicles: set[str] = set()

    def place(size: int, need_seats: bool) -> bool:
        nonlocal remaining
        for vehicle in vehs:
            if vehicle.id in used_vehicles:
                continue
            seats = vehicle.seats or size
            if need_seats and seats < min(size, len(remaining)):
                continue
            team_size = min(size, seats)
            tow = {"B": "BE", "C1": "C1E", "C": "CE"}.get(vehicle.licence, "BE")
            wants_trailer = bool(vehicle.default_trailer and vehicle.default_trailer in free_trailers)
            candidates = [m for m in remaining if m.can_drive(tow if wants_trailer else vehicle.licence)] or [
                m for m in remaining if m.can_drive(vehicle.licence)
            ]
            if not candidates:
                continue
            driver = min(candidates, key=lambda m: len(m.licences))
            rest = [m for m in remaining if m.id != driver.id]
            team = [driver] + rest[: max(0, team_size - 1)]
            unit = make(vehicle, team, None)
            if unit is None:
                continue
            units.append(unit)
            used_vehicles.add(vehicle.id)
            taken = {m.id for m in team}
            remaining = [m for m in remaining if m.id not in taken]
            return True
        return False

    # biggest team first; it takes the largest free vehicle with enough seats and a driver,
    # otherwise the team is reduced to the seats of a vehicle
    for size in sorted(sizes, reverse=True):
        if not remaining:
            break
        if not place(size, True):
            place(size, False)
    return units


# ----------------------------------------------------------------------------------- stops


def stable_fraction(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def frost_safe_from(r: SettingsResolver, plants: list[Plant], first_day: date, est: Estimator) -> date | None:
    """Earliest return date because of frost (setting returns.frost_rule / returns.frost_safe_date)."""
    rule = r.get("returns.frost_rule")
    if rule == "off":
        return None
    if rule == "frost_sensitive":
        # the plant carries its frost sensitivity (from the AI or the knowledge base, package B)
        if not any(p.frost_sensitive for p in plants):
            return None
    try:
        month, day = (int(x) for x in str(r.get("returns.frost_safe_date")).split("-"))
        return date(first_day.year, month, day)
    except ValueError:
        return None


def build_input(
    db: Session,
    tenant_id: uuid.UUID,
    start_date: date,
    days: int,
    direction: str = "pickup",
    order_ids: list[uuid.UUID] | None = None,
    scenario: dict[str, Any] | None = None,
    pins: dict[str, str] | None = None,
    forced_units: list[dict[str, Any]] | None = None,
) -> PlanningInput:
    """forced_units: snapshots of units that must exist again (fixed tours): date, vehicle, members."""
    scenario = scenario or {}
    r = SettingsResolver(db, tenant_id)
    est = Estimator(db, tenant_id)
    from app.models.core import Tenant

    tenant = db.get(Tenant, tenant_id)
    depot = (tenant.depot_lat or 48.78, tenant.depot_lon or 9.18)
    days = max(1, days + int(scenario.get("days_delta", 0)))
    dates = [start_date + timedelta(days=i) for i in range(days)]

    # ---- stops
    q = select(PickupOrder).where(
        PickupOrder.tenant_id == tenant_id,
        PickupOrder.deleted_at.is_(None),
        PickupOrder.direction == direction,
        PickupOrder.status.in_(("confirmed", "planned")),
    )
    if order_ids is not None:
        q = q.where(PickupOrder.id.in_(order_ids))
    orders = list(db.scalars(q.order_by(PickupOrder.number)))
    heights = [
        v.cargo_height_cm
        for v in db.scalars(
            select(Vehicle).where(
                Vehicle.tenant_id == tenant_id,
                Vehicle.deleted_at.is_(None),
                Vehicle.active.is_(True),
                Vehicle.kind != "trailer",
            )
        )
    ]
    lowest_cargo = min(heights) if heights else 180.0
    stops: list[StopIn] = []
    unplannable: list[dict[str, Any]] = []
    tw_mode = r.get("planning.time_windows")
    exp_share = float(r.get("learning.experiment_share"))
    for order in orders:
        address = db.get(Address, order.address_id)
        customer = db.get(Customer, order.customer_id)
        plants = est.plants_of(order)
        if not plants:
            unplannable.append({"order_id": str(order.id), "number": order.number, "reason": "no_plants"})
            continue
        if address is None or address.lat is None:
            unplannable.append(
                {"order_id": str(order.id), "number": order.number, "reason": "no_coordinates"}
            )
            continue
        paths = est.paths_for(order)
        calcs = [est.plant_calc(p, paths.get(p.access_path_id) or paths[None]) for p in plants]
        overlap_area = 0.0
        for p in plants:
            ov = float(r.get("packing.crown_overlap", *est.plant_chain(p)))
            g = geometry(p)
            if g.total_h > lowest_cargo and p.can_tilt:
                # too tall to stand in the lowest vehicle: it travels lying (length × width)
                width = max(g.pot_d, g.crown_w * (1 - (p.compressibility or 0.3) * 0.5))
                overlap_area += g.total_h * width / 10000
            else:
                overlap_area += footprint_m2(p, ov)
        frost_lo = frost_safe_from(r, plants, dates[0], est) if direction == "return" else None
        if order.fixed_date:
            allowed: set[date] | None = {order.fixed_date}
            if frost_lo and order.fixed_date < frost_lo:
                unplannable.append({"order_id": str(order.id), "number": order.number, "reason": "frost"})
                continue
        else:
            lo = order.earliest_date or dates[0]
            hi = order.latest_date or dates[-1]
            if hi < dates[0]:
                lo, hi = dates[0], dates[-1]  # overdue: any day, high priority
            if frost_lo and frost_lo > lo:
                lo = frost_lo  # frost-sensitive plants only after the frost-safe date
                if lo > dates[-1]:
                    unplannable.append({"order_id": str(order.id), "number": order.number, "reason": "frost"})
                    continue
                hi = max(hi, lo)
            allowed = {d for d in dates if lo <= d <= hi} or None
            if allowed is None and lo > dates[-1]:
                unplannable.append(
                    {"order_id": str(order.id), "number": order.number, "reason": "outside_horizon"}
                )
                continue
        windows: list[tuple[int, int, date | None]] = []
        if tw_mode != "off":
            for w in order.time_windows or []:
                try:
                    windows.append(
                        (
                            hhmm(w["from"]),
                            hhmm(w["to"]),
                            date.fromisoformat(w["date"]) if w.get("date") else None,
                        )
                    )
                except (KeyError, ValueError):
                    continue
        price = ((order.estimate or {}).get("price") or {}).get("net") or 0.0
        stop = StopIn(
            order=order,
            number=order.number,
            customer=customer.name if customer else "",
            lat=address.lat,
            lon=address.lon,
            plants=plants,
            calcs=calcs,
            weight=sum(c.vars["weight"] for c in calcs),
            area=overlap_area,
            volume=sum(volume_m3(p) for p in plants),
            min_team=int(r.get("team.min_size_per_stop", ("customer", order.customer_id))),
            dates=allowed,
            windows=windows,
            price_net=float(price),
            priority=order.priority or 0,
            experiment=exp_share > 0 and stable_fraction(f"{order.id}") < exp_share,
            paths=paths,
        )
        plant_ids = {str(p.id) for p in plants}
        for p in plants:
            for other in p.incompatible_with or []:
                if str(other) not in plant_ids:
                    stop.incompatible.add(str(other))
        if pins and stop.id in pins:
            stop.pinned_unit = pins[stop.id]
        stops.append(stop)

    # ---- resources
    all_eq = list(
        db.scalars(select(Equipment).where(Equipment.tenant_id == tenant_id, Equipment.deleted_at.is_(None)))
    )
    r.prefetch("equipment", [e.id for e in all_eq])
    shared = [equipment_info(e, r) for e in all_eq if e.vehicle_id is None and (e.count or 0) > 0]
    vrows = list(
        db.scalars(
            select(Vehicle).where(
                Vehicle.tenant_id == tenant_id, Vehicle.deleted_at.is_(None), Vehicle.active.is_(True)
            )
        )
    )
    r.prefetch("vehicle", [v.id for v in vrows])
    vehicles_base = {str(v.id): vehicle_in(db, r, v, shared, all_eq) for v in vrows}
    if direction == "return":
        # spring return: the depot time of a trip is loading (before it), not unloading (after it)
        vehicles_base = {
            vid: replace(v, unload_min=float(r.get("planning.load_min", ("vehicle", uuid.UUID(vid)))))
            for vid, v in vehicles_base.items()
        }
    for vid in scenario.get("remove_vehicle_ids", []):
        vehicles_base.pop(str(vid), None)
    for n, vid in enumerate(scenario.get("add_vehicles_like", [])):
        src = vehicles_base.get(str(vid))
        if src is not None:
            vehicles_base[f"virtual-v{n}"] = replace(
                src,
                id=f"virtual-v{n}",
                name=f"{src.name} (zusätzlich)",
                virtual=True,
                default_trailer=None,
                equipment=list(src.equipment),
            )
    member_rows = load_members(db, r, tenant_id)
    members_base = {m.id: m for _, m in member_rows}
    for sid in scenario.get("remove_staff_ids", []):
        members_base.pop(str(sid), None)
    for _ in range(int(scenario.get("remove_staff", 0))):
        # remove the person with the fewest licences and lowest carry weight (least versatile)
        if members_base:
            victim = min(members_base.values(), key=lambda m: (len(m.licences), m.solo_kg))
            members_base.pop(victim.id)
    for n in range(int(scenario.get("add_staff", 0))):
        wage = float(r.get("staff.hourly_wage")) * (1 + float(r.get("staff.employer_share_pct")) / 100)
        members_base[f"virtual-s{n}"] = Member(
            id=f"virtual-s{n}",
            name=f"Zusätzliche Person {n + 1}",
            licences={"B", "BE"},
            solo_kg=float(r.get("staff.solo_carry_kg")),
            carry_factor=float(r.get("staff.team_carry_factor")),
            carry_speed=1.0,
            drive_speed=1.0,
            hourly_cost=wage,
            max_work_min=int(float(r.get("staff.max_work_hours_day")) * 60),
            start=0,
            end=0,
            virtual=True,
        )
    real_staff_ids = [uuid.UUID(i) for i in members_base if not i.startswith("virtual")]
    real_vehicle_ids = [uuid.UUID(i) for i in vehicles_base if not i.startswith("virtual")]
    sw = day_windows(db, r, "staff", real_staff_ids, dates[0], dates[-1])
    vw = day_windows(db, r, "vehicle", real_vehicle_ids, dates[0], dates[-1])
    default_start, default_end = hhmm(r.get("planning.day_start")), hhmm(r.get("planning.day_end"))
    team_rows = list(
        db.scalars(
            select(Team)
            .where(Team.tenant_id == tenant_id, Team.deleted_at.is_(None), Team.active.is_(True))
            .order_by(Team.name)
        )
    )
    names: dict[str, str] = {m.id: m.name for m in members_base.values()}
    names.update({vid: v.name for vid, v in vehicles_base.items()})
    for s in db.scalars(select(StaffMember).where(StaffMember.tenant_id == tenant_id)):
        names.setdefault(str(s.id), s.name)  # inactive members still have a name in the hints
    for v in db.scalars(select(Vehicle).where(Vehicle.tenant_id == tenant_id)):
        names.setdefault(str(v.id), v.name)
    names.update({str(t.id): t.name for t in team_rows})
    team_issues: list[dict[str, Any]] = []
    mode = r.get("planning.form_teams")
    default_size = int(scenario.get("team_size") or r.get("planning.team_size_default"))
    units: list[Unit] = []
    for idx, day in enumerate(dates):
        members_today: list[Member] = []
        for m in members_base.values():
            if m.virtual:
                if day.weekday() < 5:
                    members_today.append(replace(m, start=default_start, end=default_end))
                continue
            w = sw[uuid.UUID(m.id)][day]
            if w.available:
                members_today.append(
                    replace(m, start=minutes(w.start, default_start), end=minutes(w.end, default_end))
                )
        vehicles_today: list[VehicleIn] = []
        trailers_today: dict[str, VehicleIn] = {}
        for vid, v in vehicles_base.items():
            if v.virtual:
                ok, st, en = day.weekday() < 5, default_start, default_end
            else:
                w = vw[uuid.UUID(vid)][day]
                ok, st, en = w.available, minutes(w.start, default_start), minutes(w.end, default_end)
            if not ok:
                continue
            vv = replace(v, start=st, end=en)
            if v.kind == "trailer":
                trailers_today[vid] = vv
            else:
                vehicles_today.append(vv)
        fixed_today = [
            (str(t.id), [str(x) for x in (t.member_ids or [])], str(t.vehicle_id) if t.vehicle_id else None)
            for t in team_rows
            if t.valid_on(day) and not _regular_day_off(t, sw, day)
        ]
        if not members_today or not vehicles_today:
            if mode == "fixed" and day.weekday() < 5:
                reason = "no_staff_today" if not members_today else "no_vehicle"
                for tid, _, _ in fixed_today:
                    team_issues.append(
                        {
                            "date": day.isoformat(),
                            "team_id": tid,
                            "team": names.get(tid, ""),
                            "reason": reason,
                            "names": [],
                            "other_team": None,
                        }
                    )
            continue
        forced_today = [
            (f"forced:{f['key']}", [m["id"] for m in f.get("members", [])], f.get("vehicle_id"))
            for f in (forced_units or [])
            if f.get("date") == day.isoformat()
        ]
        seen: set[str] = set()
        forced_today = [f for f in forced_today if not (f[0] in seen or seen.add(f[0]))]
        units += form_units(
            r,
            day,
            idx,
            members_today,
            vehicles_today,
            trailers_today,
            forced_today + fixed_today,
            stops,
            mode,
            default_size,
            scenario.get("team_size"),
            issues=team_issues if mode == "fixed" else None,
            names=names,
        )
    settings = {
        "skip_penalty": float(r.get("planning.skip_penalty")),
        "allow_over_limit": bool(r.get("team.plan_over_limit")),
        "time_windows": tw_mode,
        "tw_penalty": float(r.get("planning.time_window_penalty_min")),
        "overtime_penalty": float(r.get("planning.overtime_penalty_min")),
        "overtime_surcharge": float(r.get("costs.overtime_surcharge_pct")) / 100,
        "objective": r.get("planning.objective"),
        "w_vehicle": float(r.get("planning.weight_vehicle_cost")),
        "w_labour": float(r.get("planning.weight_labour_cost")),
        "first_solution": r.get("planning.first_solution"),
        "metaheuristic": r.get("planning.metaheuristic"),
        "time_limit_s": float(scenario.get("time_limit_s") or r.get("planning.time_limit_s")),
        "cluster_max": int(r.get("planning.cluster_max_stops")),
        "day_preference": float(r.get("planning.day_preference_eur")),
        "unit_fixed": float(r.get("planning.unit_fixed_eur")),
        "parking_min": float(r.get("drive.parking_min")),
        "pack_retry_limit": int(r.get("planning.pack_retry_limit")),
        "capacity_shrink": float(r.get("planning.capacity_shrink")),
        "quantile_factor": est.quantile_factor,
    }
    inp = PlanningInput(
        direction=direction,
        tenant_id=tenant_id,
        depot=depot,
        dates=dates,
        units=units,
        stops=stops,
        unplannable=unplannable,
        estimator=est,
        shared_equipment=shared,
        settings=settings,
        team_mode=mode,
        team_issues=team_issues,
        fixed_teams=[
            {
                "id": str(t.id),
                "name": t.name,
                "member_ids": [str(x) for x in (t.member_ids or [])],
                "vehicle_id": str(t.vehicle_id) if t.vehicle_id else None,
            }
            for t in team_rows
        ],
        names=names,
        staff_ids=[m.id for m in members_base.values() if not m.virtual],
        vehicles=[v for v in vehicles_base.values() if v.kind != "trailer"],
    )
    return inp


def _regular_day_off(team: Team, sw: dict, day: date) -> bool:
    """A team without fixed weekdays does not work on days its members normally have off."""
    if team.weekdays:
        return False
    windows = [sw.get(uuid.UUID(str(m)), {}).get(day) for m in team.member_ids or []]
    windows = [w for w in windows if w is not None]
    return bool(windows) and all(not w.available and w.reason in ("weekend", "no_pattern") for w in windows)


def fits_geometry(stop: StopIn, unit: Unit) -> bool:
    """Coarse check: every plant fits through a door and under the roof of the vehicle or trailer."""
    spaces = [unit.vehicle] + ([unit.trailer] if unit.trailer else [])
    for p in stop.plants:
        g = geometry(p)
        pot = g.pot_d if g.pot_shape == "round" else max(g.pot_l, g.pot_w)
        ok = False
        for v in spaces:
            if pot > v.door_w or pot > v.width:
                continue
            if g.total_h <= min(v.height, v.door_h + 20):
                ok = True
            elif p.can_tilt and g.total_h <= v.length and min(g.footprint_w, pot) <= v.door_h:
                ok = True
            if ok:
                break
        if not ok:
            return False
    return True


def ceil_min(x: float) -> int:
    return int(math.ceil(max(0.0, x) - 1e-9))

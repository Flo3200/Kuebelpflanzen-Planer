"""Time, labour, cost and price estimate for a pickup (one stop).

Duration (minutes on site) drives the tour plan; labour time = duration × team size drives costs.
Both are always kept separately. All numbers come from formulas and settings.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import NormalDist
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fleet.layout import module_vehicles
from app.formula.parser import FormulaError
from app.formula.store import CompiledFormula, load_active
from app.models.core import Tenant
from app.models.masterdata import Equipment, Species, StaffMember, Vehicle
from app.models.orders import AccessPath, Address, PathSegment, PickupOrder, Plant
from app.routing.provider import provider_for
from app.settings.service import SettingsResolver
from app.timemodel.costitems import load_items as load_cost_items
from app.timemodel.costitems import order_costs as order_cost_items
from app.timemodel.plantfill import geometry, volume_m3
from app.timemodel.teams import CrewResult, CrewRules, EquipmentInfo, PathInfo, required_crew

ROUGH = {"gravel", "lawn", "soil"}


@dataclass
class PlantCalc:
    plant: Plant
    vars: dict[str, Any]
    crew: CrewResult


def path_info(segments: list[PathSegment], confirmed_length: float | None, default_length: float) -> PathInfo:
    if not segments:
        return PathInfo(confirmed_length or default_length, 0.0, 0, None, 0, 0.0, False, False, [])
    length = sum(s.length_m or 0 for s in segments)
    carry_height = sum(abs(s.height_diff_m or 0) for s in segments if not s.elevator and s.kind != "elevator")
    steps = sum(s.steps or 0 for s in segments if not s.elevator)
    if carry_height == 0 and steps:
        carry_height = steps * 0.17
    widths = [s.min_width_cm for s in segments if s.min_width_cm]
    return PathInfo(
        length_m=confirmed_length or length or default_length,
        carry_height_m=carry_height,
        steps=steps,
        min_width_cm=min(widths) if widths else None,
        doors=sum(s.doors or 0 for s in segments),
        max_slope_pct=max((s.slope_pct or 0 for s in segments), default=0.0),
        has_stairs=any((s.steps or 0) > 0 or s.kind == "stairs" for s in segments),
        elevator=any(s.elevator or s.kind == "elevator" for s in segments),
        surfaces=sorted({s.surface for s in segments if s.surface}),
    )


def equipment_info(e: Equipment, resolver: SettingsResolver) -> EquipmentInfo:
    return EquipmentInfo(
        id=str(e.id),
        name=e.name,
        kind=e.kind,
        capacity_kg=e.capacity_kg,
        carry_time_factor=e.carry_time_factor or 1.0,
        solo_limit_kg=e.solo_limit_kg,
        usable_on_stairs=e.usable_on_stairs,
        surfaces=list(e.surfaces or []),
        min_path_width_cm=e.min_path_width_cm,
        vehicle_id=str(e.vehicle_id) if e.vehicle_id else None,
        cost_per_use=float(resolver.get("costs.equipment_per_use", ("equipment", e.id))),
    )


class Estimator:
    """Caches settings, formulas, equipment and staff costs for one tenant."""

    def __init__(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        *,
        time_formula: CompiledFormula | None = None,
        params: dict[str, float] | None = None,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.resolver = SettingsResolver(db, tenant_id)
        r = self.resolver
        self.time = time_formula or load_active(db, tenant_id, "time", int(r.get("time.formula_tier")))
        self.params = params
        self.price_formula = load_active(db, tenant_id, "price", 1)
        self.tenant = db.get(Tenant, tenant_id)
        eqs = list(
            db.scalars(
                select(Equipment).where(Equipment.tenant_id == tenant_id, Equipment.deleted_at.is_(None))
            )
        )
        r.prefetch("equipment", [e.id for e in eqs])
        self.equipment = [equipment_info(e, r) for e in eqs if (e.count or 0) > 0]
        staff = list(
            db.scalars(
                select(StaffMember).where(
                    StaffMember.tenant_id == tenant_id,
                    StaffMember.deleted_at.is_(None),
                    StaffMember.active.is_(True),
                )
            )
        )
        r.prefetch("staff", [s.id for s in staff])
        rates = [self.hourly_cost(s.id) for s in staff]
        self.avg_hourly_cost = sum(rates) / len(rates) if rates else self.hourly_cost(None)
        self.n_staff = len(staff)
        self.n_vehicles = (
            db.scalar(
                select(func.count())
                .select_from(Vehicle)
                .where(
                    Vehicle.tenant_id == tenant_id,
                    Vehicle.deleted_at.is_(None),
                    Vehicle.active.is_(True),
                    Vehicle.kind != "trailer",
                )
            )
            or 0
        )
        self.cost_items = load_cost_items(db, tenant_id)
        self.module_vehicles = {k: len(v) for k, v in module_vehicles(db, tenant_id).items()}
        self.species: dict[uuid.UUID, Species] = {}
        self.routing = provider_for(r)
        # spring return: setting plants down at the customer may take longer or shorter
        self.return_factor = float(r.get("returns.time_factor"))
        q = float(r.get("time.planning_quantile"))
        self.sigma = float(r.get("time.error_sigma"))
        self.quantile_factor = math.exp(NormalDist().inv_cdf(q) * self.sigma) if 0 < q < 1 else 1.0
        self.rules = CrewRules(
            solo_kg=float(r.get("staff.solo_carry_kg")),
            carry_factor=float(r.get("staff.team_carry_factor")),
            grip_diameter_cm=float(r.get("team.grip_diameter_cm")),
            grip_height_cm=float(r.get("team.grip_height_cm")),
            stairs_weight_kg=float(r.get("team.stairs_weight_kg")),
            stairs_extra=int(r.get("team.stairs_extra_persons")),
            steep_slope_pct=float(r.get("team.steep_slope_pct")),
            narrow_extra=int(r.get("team.narrow_extra_persons")),
            max_size=int(r.get("team.max_size")),
        )

    # ------------------------------------------------------------------ helpers

    def hourly_cost(self, staff_id: uuid.UUID | None) -> float:
        chain = [("staff", staff_id)] if staff_id else []
        wage = float(self.resolver.get("staff.hourly_wage", *chain))
        share = float(self.resolver.get("staff.employer_share_pct", *chain))
        return wage * (1 + share / 100)

    def species_of(self, plant: Plant) -> Species | None:
        if plant.species_id is None:
            return None
        if plant.species_id not in self.species:
            s = self.db.get(Species, plant.species_id)
            if s is not None:
                self.species[plant.species_id] = s
        return self.species.get(plant.species_id)

    def plant_chain(self, plant: Plant) -> list[tuple[str, uuid.UUID]]:
        chain: list[tuple[str, uuid.UUID]] = [("plant", plant.id)]
        sp = self.species_of(plant)
        if sp is not None:
            chain.append(("species", sp.id))
            if sp.overrides_id:
                chain.append(("species", sp.overrides_id))
        return chain

    def rules_for(self, plant: Plant) -> CrewRules:
        chain = self.plant_chain(plant)
        r = self.resolver
        return CrewRules(
            **{
                **self.rules.__dict__,
                "grip_diameter_cm": float(r.get("team.grip_diameter_cm", *chain)),
                "grip_height_cm": float(r.get("team.grip_height_cm", *chain)),
            }
        )

    # ------------------------------------------------------------------ per plant

    def plant_calc(
        self,
        plant: Plant,
        path: PathInfo,
        *,
        equipment: list[EquipmentInfo] | None = None,
        solo_limits: list[float] | None = None,
        carry_factor: float | None = None,
    ) -> PlantCalc:
        g = geometry(plant)
        weight = float(plant.weight_measured_kg or plant.weight_kg or 0)
        compress = plant.compressibility if plant.compressibility is not None else 0.3
        passage = max(
            g.pot_d if g.pot_shape == "round" else max(g.pot_l, g.pot_w), g.crown_w * (1 - compress)
        )
        clearance = float(self.resolver.get("time.narrow_clearance_cm"))
        narrow = bool(path.min_width_cm and path.min_width_cm < passage + clearance)
        rules = self.rules_for(plant)
        if carry_factor is not None:
            rules.carry_factor = carry_factor
        crew = required_crew(
            weight,
            g.pot_d,
            g.total_h,
            path,
            rules,
            self.equipment if equipment is None else equipment,
            narrow,
            plant.team_size_override,
            solo_limits,
        )
        variables = {
            "weight": weight,
            "pot_diameter": g.pot_d,
            "pot_height": g.pot_h,
            "height": g.total_h,
            "crown_width": g.crown_w,
            "passage_width": passage,
            "volume": volume_m3(plant),
            "crew": crew.crew,
            "can_tilt": 1.0 if plant.can_tilt else 0.0,
            "sensitive": 1.0 if plant.sensitive else 0.0,
            "narrow_factor": float(self.resolver.get("time.narrow_factor")) if narrow else 1.0,
            "equipment_factor": crew.equipment.carry_time_factor if crew.equipment else 1.0,
            "path_length": path.length_m,
            "height_meters": path.carry_height_m,
            "steps": float(path.steps),
            "min_width": path.min_width_cm or 999.0,
            "doors": float(path.doors),
            "slope": path.max_slope_pct,
            "has_stairs": 1.0 if path.has_stairs else 0.0,
            "elevator": 1.0 if path.elevator else 0.0,
            "rough_surface": 1.0 if set(path.surfaces) & ROUGH else 0.0,
        }
        return PlantCalc(plant, variables, crew)

    def paths_for(self, order: PickupOrder) -> dict[uuid.UUID | None, PathInfo]:
        source = order.return_of_id or order.id
        default = float(self.resolver.get("time.default_path_length_m"))
        out: dict[uuid.UUID | None, PathInfo] = {}
        first: PathInfo | None = None
        for p in self.db.scalars(
            select(AccessPath).where(AccessPath.order_id == source).order_by(AccessPath.created_at)
        ):
            segs = list(
                self.db.scalars(
                    select(PathSegment).where(PathSegment.path_id == p.id).order_by(PathSegment.position)
                )
            )
            info = path_info(segs, p.length_confirmed_m, default)
            out[p.id] = info
            first = first or info
        out[None] = first or PathInfo(default, 0.0, 0, None, 0, 0.0, False, False, [])
        return out

    def plants_of(self, order: PickupOrder) -> list[Plant]:
        source = order.return_of_id or order.id
        return list(
            self.db.scalars(
                select(Plant)
                .where(Plant.order_id == source, Plant.deleted_at.is_(None))
                .order_by(Plant.number)
            )
        )

    # ------------------------------------------------------------------ per stop

    def stop_duration(
        self,
        calcs: list[PlantCalc],
        team_size: int,
        speed: float = 1.0,
        params: dict[str, float] | None = None,
    ) -> float:
        if not calcs:
            return 0.0
        plants = [dict(c.vars) for c in calcs]
        stop_vars = {
            "team": float(team_size),
            "speed": max(0.1, speed),
            "n_plants": float(len(calcs)),
            "total_weight": sum(c.vars["weight"] for c in calcs),
            "walk_speed": float(self.resolver.get("time.walk_speed_m_min")),
            "max_crew": float(max(c.crew.crew for c in calcs)),
        }
        out = self.time.run(stop_vars, plants, params if params is not None else self.params)
        for c, p in zip(calcs, plants, strict=True):
            c.vars["work"] = p.get("work")
        return max(0.0, float(out["duration"]))

    def direction_factor(self, order: PickupOrder) -> float:
        return self.return_factor if order.direction == "return" else 1.0

    def stop_estimate(
        self, calcs: list[PlantCalc], *, min_team: int | None = None, speed: float = 1.0, factor: float = 1.0
    ) -> dict[str, Any]:
        max_crew = max((c.crew.crew for c in calcs), default=1)
        team = max(max_crew, min_team or int(self.resolver.get("team.min_size_per_stop")))
        max_size = max(team, int(self.resolver.get("team.max_size")))
        durations = {
            m: round(self.stop_duration(calcs, m, speed) * factor, 2) for m in range(team, max_size + 1)
        }
        duration = durations[team]
        return {
            "team_size": team,
            "duration_min": round(duration, 1),
            "labour_min": round(duration * team, 1),
            "planning_duration_min": round(duration * self.quantile_factor, 1),
            "durations_by_team": durations,
        }

    # ------------------------------------------------------------------ order

    def distance_km(self, address: Address | None) -> tuple[float | None, float | None]:
        t = self.tenant
        if address is None or address.lat is None or t is None or t.depot_lat is None:
            return None, None
        m = self.routing.matrix([(t.depot_lat, t.depot_lon), (address.lat, address.lon)])
        return m.distance_km[0][1], m.duration_min[0][1]

    def order_estimate(self, order: PickupOrder) -> dict[str, Any]:
        r = self.resolver
        warnings: list[str] = []
        paths = self.paths_for(order)
        plants = self.plants_of(order)
        calcs = [self.plant_calc(p, paths.get(p.access_path_id) or paths[None]) for p in plants]
        for c in calcs:
            if c.crew.exceeds_max:
                warnings.append(f"plant_exceeds_team:{c.plant.number}")
            if not c.plant.weight_kg and not c.plant.weight_measured_kg:
                warnings.append(f"no_weight:{c.plant.number}")
        try:
            stop = self.stop_estimate(calcs, factor=self.direction_factor(order))
        except FormulaError as exc:
            return {"error": f"{exc.code}: {exc.detail}", "computed_at": datetime.now(UTC).isoformat()}
        address = self.db.get(Address, order.address_id)
        dist, drive_min = self.distance_km(address)
        if dist is None:
            warnings.append("no_coordinates")
        n_typical = max(1, int(r.get("pricing.typical_tour_stops")))
        local_km = float(r.get("pricing.local_detour_km"))
        share_km = (2 * dist / n_typical + local_km) if dist is not None else local_km
        avg_speed = float(r.get("drive.avg_speed_kmh"))
        share_drive_min = share_km / max(avg_speed, 1) * 60 + float(
            r.get("drive.parking_min", ("customer", order.customer_id))
        )
        team = stop["team_size"]
        # costs (pre-planning, average vehicle and staff)
        labour_cost = stop["labour_min"] / 60 * self.avg_hourly_cost
        drive_labour_cost = share_drive_min * team / 60 * self.avg_hourly_cost
        per_km = float(r.get("costs.vehicle_per_km")) + float(r.get("costs.fuel_l_per_100km")) / 100 * float(
            r.get("costs.fuel_price")
        )
        vehicle_cost = share_km * per_km + (share_drive_min + stop["duration_min"]) / 60 * float(
            r.get("costs.vehicle_per_hour")
        )
        used_eq = {c.crew.equipment.id: c.crew.equipment for c in calcs if c.crew.equipment}
        equipment_cost = sum(e.cost_per_use for e in used_eq.values())
        custom_cost, custom_lines = order_cost_items(
            self.cost_items,
            n_vehicles=self.n_vehicles,
            n_staff=self.n_staff,
            team=team,
            km=share_km,
            hours=(share_drive_min + stop["duration_min"]) / 60,
            plants=len(calcs),
            stops_per_tour=n_typical,
            workdays_per_month=int(r.get("costs.workdays_per_month")),
            module_vehicles=self.module_vehicles,
        )
        direct = labour_cost + drive_labour_cost + vehicle_cost + equipment_cost + custom_cost
        self_cost = direct * (1 + float(r.get("costs.overhead_pct")) / 100)
        target = self_cost * (1 + float(r.get("costs.margin_pct")) / 100)
        price = self.price(
            order, stop, len(calcs), sum(c.vars["weight"] for c in calcs), dist, share_km, self_cost
        )
        return {
            **stop,
            "plants": [
                {
                    "id": str(c.plant.id),
                    "number": c.plant.number,
                    "crew": c.crew.crew,
                    "needed": c.crew.needed,
                    "reasons": c.crew.reasons,
                    "work": round(float(c.vars.get("work") or 0), 2),
                    "equipment": c.crew.equipment.name if c.crew.equipment else None,
                    "narrow": c.vars["narrow_factor"] > 1,
                    "weight": c.vars["weight"],
                }
                for c in calcs
            ],
            "warnings": warnings,
            "distance_km": round(dist, 1) if dist is not None else None,
            "drive": {
                "share_km": round(share_km, 1),
                "share_min": round(share_drive_min, 1),
                "one_way_min": round(drive_min, 1) if drive_min is not None else None,
            },
            "costs": {
                "labour": round(labour_cost, 2),
                "drive_labour": round(drive_labour_cost, 2),
                "vehicle": round(vehicle_cost, 2),
                "equipment": round(equipment_cost, 2),
                "custom": round(custom_cost, 2),
                "custom_items": custom_lines,
                "direct": round(direct, 2),
                "self_cost": round(self_cost, 2),
                "target_price_net": round(target, 2),
                "hourly_cost": round(self.avg_hourly_cost, 2),
            },
            "price": price,
            "formula": {
                "time": {
                    "name": self.time.formula.name,
                    "tier": self.time.formula.tier,
                    "version": self.time.version.version,
                    "tenant_override": self.time.formula.tenant_id is not None,
                },
                "price": {"version": self.price_formula.version.version},
                "quantile": float(r.get("time.planning_quantile")),
                "quantile_factor": round(self.quantile_factor, 3),
            },
            "computed_at": datetime.now(UTC).isoformat(),
        }

    def distance_surcharge(self, dist: float | None, share_km: float) -> float:
        r = self.resolver
        mode = r.get("pricing.distance_mode")
        rate = float(r.get("pricing.distance_rate_km"))
        if mode == "off" or (dist is None and mode != "detour"):
            return 0.0
        if mode == "distance":
            return max(0.0, dist - float(r.get("pricing.distance_free_km"))) * rate
        if mode == "zones":
            for zone in sorted(r.get("pricing.zones") or [], key=lambda z: z.get("max_km", 0)):
                if dist <= float(zone.get("max_km", 0)):
                    return float(zone.get("surcharge", 0))
            return 0.0
        return share_km * rate  # detour

    def price(
        self,
        order: PickupOrder,
        stop: dict[str, Any],
        n_plants: int,
        total_weight: float,
        dist: float | None,
        share_km: float,
        self_cost: float,
    ) -> dict[str, Any]:
        r = self.resolver
        cust = ("customer", order.customer_id)
        surcharge = self.distance_surcharge(dist, share_km)
        variables = {
            "labour_min": stop["labour_min"],
            "duration_min": stop["duration_min"],
            "n_plants": float(n_plants),
            "total_weight": total_weight,
            "distance_km": dist or 0.0,
            "drive_share_km": share_km,
            "distance_surcharge": surcharge,
            "base_price": float(r.get("pricing.base_price", cust)),
            "rate_per_labour_minute": float(r.get("pricing.rate_per_labour_min", cust)),
            "per_plant_fee": float(r.get("pricing.per_plant_fee", cust)),
            "minimum_price": float(r.get("pricing.minimum_price", cust)),
            "self_cost": self_cost,
            "team": float(stop["team_size"]),
        }
        try:
            value = float(self.price_formula.run(variables, [])["price"])
        except FormulaError as exc:
            return {"error": f"{exc.code}: {exc.detail}"}
        if order.direction == "return":
            mode = r.get("returns.price_mode", cust)
            if mode == "included":
                value = 0.0  # the return is part of the pickup / overwintering price
            elif mode == "factor":
                value *= float(r.get("returns.price_factor", cust))
        step = float(r.get("pricing.rounding"))
        if step > 0:
            value = round(value / step) * step
        vat = float(r.get("costs.vat_pct"))
        if r.get("pricing.prices_include_vat"):
            gross, net = value, value / (1 + vat / 100)
        else:
            net, gross = value, value * (1 + vat / 100)
        return {
            "gross": round(gross, 2),
            "net": round(net, 2),
            "vat_pct": vat,
            "distance_surcharge": round(surcharge, 2),
            "coverage_pct": round(net / self_cost * 100, 1) if self_cost > 0 else None,
            "margin_eur": round(net - self_cost, 2),
            "components": {
                k: round(v, 2)
                for k, v in variables.items()
                if k in ("base_price", "rate_per_labour_minute", "per_plant_fee", "minimum_price")
            },
        }

"""Complete missing plant values from species defaults and settings; estimate the weight.

Every value that is filled in here is listed in plant.estimated_fields so the UI can mark it
as "geschätzt". Values entered by people or confirmed from AI drafts are never overwritten.

Weight model (all coefficients are settings or species attributes):
  pot volume  V_pot = π (d/2)² h · taper     (square: l · w · h)         [litres]
  soil        V_pot · fill · soil_kg_per_l
  pot itself  V_pot · material_kg_per_l[material]
  crown       V_crown · crown_density · plant_kg_per_l
  trunk       trunk_kg_per_m · crown_start
  weight      (soil + pot + crown + trunk) · calibration_factor
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.masterdata import Species
from app.models.orders import Plant
from app.settings.service import SettingsResolver


@dataclass
class Geometry:
    pot_shape: str
    pot_d: float  # diameter or the larger side, cm
    pot_l: float
    pot_w: float
    pot_h: float
    crown_shape: str
    crown_w: float
    crown_h: float
    crown_start: float
    total_h: float

    @property
    def footprint_w(self) -> float:
        """Largest horizontal extent (cm)."""
        return max(self.pot_d if self.pot_shape == "round" else max(self.pot_l, self.pot_w), self.crown_w)


def pot_volume_l(pot_shape: str, d: float, l_cm: float, w: float, h: float, taper: float) -> float:
    if pot_shape == "square":
        return l_cm * w * h * (0.5 + taper / 2) / 1000.0
    return math.pi * (d / 2) ** 2 * h * taper / 1000.0


def crown_volume_l(shape: str, width: float, height: float) -> float:
    r = width / 2
    if shape == "cone":
        v = math.pi * r * r * height / 3
    elif shape == "sphere":
        v = 4 / 3 * math.pi * r * r * (height / 2)  # ellipsoid
    elif shape == "column":
        v = math.pi * r * r * height * 0.8
    elif shape == "cylinder":
        v = math.pi * r * r * height
    else:  # free form: between cone and cylinder
        v = math.pi * r * r * height * 0.55
    return v / 1000.0


def _set(plant: Plant, field: str, value: Any, estimated: set[str]) -> None:
    if getattr(plant, field) is None:
        setattr(plant, field, value)
        estimated.add(field)


def complete_plant(
    db: Session, plant: Plant, resolver: SettingsResolver, species: Species | None = None
) -> Plant:
    """Fill missing values in place; recompute weight unless it was entered or measured."""
    if species is None and plant.species_id:
        species = db.get(Species, plant.species_id)
    estimated: set[str] = set(plant.estimated_fields or [])

    if plant.pot_shape == "square":
        if plant.pot_length_cm is None and plant.pot_diameter_cm is not None:
            _set(plant, "pot_length_cm", plant.pot_diameter_cm, estimated)
        _set(plant, "pot_length_cm", resolver.get("weight.default_pot_diameter_cm"), estimated)
        _set(plant, "pot_width_cm", plant.pot_length_cm, estimated)
    else:
        _set(plant, "pot_diameter_cm", resolver.get("weight.default_pot_diameter_cm"), estimated)
    d = plant.pot_diameter_cm if plant.pot_shape != "square" else max(plant.pot_length_cm, plant.pot_width_cm)
    _set(plant, "pot_height_cm", round(d * 0.9, 1), estimated)
    _set(plant, "pot_material", "plastic", estimated)

    crown_shape = species.crown_shape if species else "sphere"
    _set(plant, "crown_shape", crown_shape, estimated)
    typical = species.typical_height_cm if species and species.typical_height_cm else None
    if plant.total_height_cm is None and plant.crown_height_cm is not None:
        _set(
            plant,
            "total_height_cm",
            round(plant.pot_height_cm + plant.crown_height_cm + (plant.crown_start_cm or 0), 1),
            estimated,
        )
    _set(plant, "total_height_cm", typical or round(plant.pot_height_cm * 3.2, 1), estimated)
    _set(
        plant,
        "crown_start_cm",
        round(max(0.0, (plant.total_height_cm - plant.pot_height_cm) * 0.25), 1),
        estimated,
    )
    _set(
        plant,
        "crown_height_cm",
        round(max(10.0, plant.total_height_cm - plant.pot_height_cm - plant.crown_start_cm), 1),
        estimated,
    )
    _set(plant, "crown_width_cm", round(d * resolver.get("weight.default_crown_ratio"), 1), estimated)
    _set(plant, "crown_density", species.crown_density if species else 0.5, estimated)
    _set(plant, "compressibility", species.compressibility if species else 0.3, estimated)
    if plant.can_tilt is None:
        plant.can_tilt = bool(species.can_tilt) if species else False
        estimated.add("can_tilt")
    if plant.sensitive is None:
        plant.sensitive = bool(species.sensitive) if species else False
        estimated.add("sensitive")
    if plant.frost_sensitive is None:
        plant.frost_sensitive = (species.frost_sensitivity == "tender") if species else False
        estimated.add("frost_sensitive")

    if plant.weight_kg is None or "weight_kg" in estimated:
        weight, uncertainty = estimate_weight(plant, resolver, species, estimated)
        plant.weight_kg = round(weight, 1)
        plant.weight_uncertainty_kg = round(uncertainty, 1)
        estimated.add("weight_kg")
    plant.estimated_fields = sorted(estimated)
    return plant


def estimate_weight(
    plant: Plant, resolver: SettingsResolver, species: Species | None, estimated: set[str]
) -> tuple[float, float]:
    taper = resolver.get("weight.pot_taper")
    fill = resolver.get("weight.pot_fill")
    vol = pot_volume_l(
        plant.pot_shape or "round",
        plant.pot_diameter_cm or 0,
        plant.pot_length_cm or 0,
        plant.pot_width_cm or 0,
        plant.pot_height_cm or 0,
        taper,
    )
    soil_density = species.soil_kg_per_l if species else 1.3
    plant_density = species.plant_kg_per_l if species else 0.03
    trunk = species.trunk_kg_per_m if species else 1.5
    materials = resolver.get("weight.pot_material_kg_per_l") or {}
    pot_factor = float(materials.get(plant.pot_material or "plastic", 0.1))
    crown_v = crown_volume_l(
        plant.crown_shape or "sphere", plant.crown_width_cm or 0, plant.crown_height_cm or 0
    )
    weight = (
        vol * fill * soil_density
        + vol * pot_factor
        + crown_v * (plant.crown_density or 0.5) * plant_density
        + trunk * (plant.crown_start_cm or 0) / 100.0
    ) * resolver.get("weight.calibration_factor")
    rel = resolver.get("weight.uncertainty_pct") / 100.0
    dims_estimated = {"pot_diameter_cm", "pot_height_cm", "pot_length_cm"} & estimated
    if dims_estimated:
        rel *= 2
    return weight, weight * rel


def geometry(plant: Plant) -> Geometry:
    pot_d = plant.pot_diameter_cm or max(plant.pot_length_cm or 0, plant.pot_width_cm or 0) or 40
    return Geometry(
        pot_shape=plant.pot_shape or "round",
        pot_d=pot_d,
        pot_l=plant.pot_length_cm or pot_d,
        pot_w=plant.pot_width_cm or pot_d,
        pot_h=plant.pot_height_cm or pot_d * 0.9,
        crown_shape=plant.crown_shape or "sphere",
        crown_w=plant.crown_width_cm or pot_d * 1.5,
        crown_h=plant.crown_height_cm or 80,
        crown_start=plant.crown_start_cm or 0,
        total_h=plant.total_height_cm or ((plant.pot_height_cm or pot_d) + (plant.crown_height_cm or 80)),
    )


def footprint_m2(plant: Plant, overlap: float = 0.0) -> float:
    """Floor area a plant needs standing upright (crown may overlap neighbours by `overlap`)."""
    g = geometry(plant)
    pot_area = (math.pi * (g.pot_d / 2) ** 2) if g.pot_shape == "round" else g.pot_l * g.pot_w
    crown_r = g.crown_w / 2 * (1 - overlap)
    crown_area = math.pi * crown_r**2
    return max(pot_area, crown_area) / 10000.0


def volume_m3(plant: Plant) -> float:
    """Bounding volume (for the planner's volume dimension)."""
    g = geometry(plant)
    w = g.footprint_w
    return w * w * g.total_h / 1e6

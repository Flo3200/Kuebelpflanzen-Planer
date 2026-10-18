"""Internal knowledge base of plant species (package B).

Tenants no longer maintain species. The AI names the species of each plant and its properties
(weight, compressibility, tip tendency, frost sensitivity) and stores them on the plant. Values the
AI leaves open are copied from the knowledge base: the global species rows maintained by the admin
(tenant overrides from before stay valid for their tenant). All calculations read the plant only.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.masterdata import Species
from app.models.orders import Plant

# plant column -> how to derive it from a knowledge-base species
TRAITS: dict[str, Any] = {
    "crown_shape": lambda s: s.crown_shape,
    "crown_density": lambda s: s.crown_density,
    "compressibility": lambda s: s.compressibility,
    "tip_tendency": lambda s: s.tip_tendency,
    "soil_kg_per_l": lambda s: s.soil_kg_per_l,
    "plant_kg_per_l": lambda s: s.plant_kg_per_l,
    "trunk_kg_per_m": lambda s: s.trunk_kg_per_m,
    "can_tilt": lambda s: bool(s.can_tilt),
    "sensitive": lambda s: bool(s.sensitive),
    "frost_sensitive": lambda s: s.frost_sensitivity == "tender",
}
# used when neither the AI nor the knowledge base knows the species
DEFAULTS: dict[str, Any] = {
    "crown_shape": "sphere",
    "crown_density": 0.5,
    "compressibility": 0.3,
    "tip_tendency": 0.3,
    "soil_kg_per_l": 1.3,
    "plant_kg_per_l": 0.03,
    "trunk_kg_per_m": 1.5,
    "can_tilt": False,
    "sensitive": False,
    "frost_sensitive": False,
}
# traits the AI may return with a confidence (message intake and photo analysis)
AI_TRAITS = ("compressibility", "tip_tendency", "can_tilt", "frost_sensitive", "sensitive", "crown_density")


def catalog(db: Session, tenant_id: uuid.UUID | None) -> list[Species]:
    """Effective knowledge base for a tenant: global rows, replaced by old tenant overrides."""
    rows = list(
        db.scalars(
            select(Species)
            .where(
                or_(Species.tenant_id.is_(None), Species.tenant_id == tenant_id)
                if tenant_id
                else Species.tenant_id.is_(None),
                Species.deleted_at.is_(None),
            )
            .order_by(Species.name)
        )
    )
    overridden = {r.overrides_id for r in rows if r.tenant_id is not None and r.overrides_id}
    return [r for r in rows if r.id not in overridden]


def names(db: Session, tenant_id: uuid.UUID | None) -> list[str]:
    out: list[str] = []
    for s in catalog(db, tenant_id):
        out.append(s.name)
        out += [str(a) for a in (s.aliases or [])]
    return out


def match(db: Session, tenant_id: uuid.UUID | None, name: str | None) -> Species | None:
    """Knowledge-base species for a name (exact name, botanical name or alias; else a close prefix)."""
    if not name:
        return None
    low = name.lower().strip()
    best = None
    for s in catalog(db, tenant_id):
        for c in (s.name, s.botanical_name or "", *[str(a) for a in (s.aliases or [])]):
            c = c.lower()
            if not c:
                continue
            if c == low:
                return s
            if best is None and (
                low.startswith(c[: max(4, len(c) - 2)]) or c.startswith(low[: max(4, len(low) - 2)])
            ):
                best = s
    return best


def traits_of(species: Species | None) -> dict[str, Any]:
    if species is None:
        return dict(DEFAULTS)
    return {k: f(species) for k, f in TRAITS.items()}


def species_for_plant(db: Session, plant: Plant) -> Species | None:
    """Knowledge-base entry of a plant: the stored link, else a match of the species name."""
    if plant.species_id:
        sp = db.get(Species, plant.species_id)
        if sp is not None:
            return sp
    sp = match(db, plant.tenant_id, plant.species_name)
    if sp is not None:
        plant.species_id = sp.id
    return sp


def fill_from_knowledge(
    db: Session, plant: Plant, estimated: set[str], species: Species | None = None
) -> None:
    """Copy missing traits from the knowledge base to the plant (marked as estimated)."""
    sp = species if species is not None else species_for_plant(db, plant)
    if sp is not None and not plant.species_name:
        plant.species_name = sp.name
        estimated.add("species_name")
    for field, value in traits_of(sp).items():
        if getattr(plant, field) is None:
            setattr(plant, field, value)
            estimated.add(field)
    if sp is not None and not plant.species_source:
        plant.species_source = "knowledge"


def typical_height(species: Species | None) -> float | None:
    return species.typical_height_cm if species is not None and species.typical_height_cm else None

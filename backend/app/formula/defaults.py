"""Built-in formulas (seeded as global version 1) and the documented variables.

Every value here is only a starting point: the admin edits formulas and parameters in the UI,
tenants may override them, and learnable parameters are fitted to measurements (phase 6).
"""

from __future__ import annotations

from typing import Any

# Variables available to formulas, with level, unit and a German explanation (labels in de.json).
TIME_VARIABLES: dict[str, dict[str, Any]] = {
    # plant level
    "weight": {"level": "plant", "unit": "kg"},
    "pot_diameter": {"level": "plant", "unit": "cm"},
    "pot_height": {"level": "plant", "unit": "cm"},
    "height": {"level": "plant", "unit": "cm"},
    "crown_width": {"level": "plant", "unit": "cm"},
    "passage_width": {"level": "plant", "unit": "cm"},
    "volume": {"level": "plant", "unit": "m³"},
    "crew": {"level": "plant", "unit": "Pers."},
    "can_tilt": {"level": "plant", "unit": "0/1"},
    "sensitive": {"level": "plant", "unit": "0/1"},
    "narrow_factor": {"level": "plant", "unit": "×"},
    "equipment_factor": {"level": "plant", "unit": "×"},
    "path_length": {"level": "plant", "unit": "m"},
    "height_meters": {"level": "plant", "unit": "m"},
    "steps": {"level": "plant", "unit": ""},
    "min_width": {"level": "plant", "unit": "cm"},
    "doors": {"level": "plant", "unit": ""},
    "slope": {"level": "plant", "unit": "%"},
    "has_stairs": {"level": "plant", "unit": "0/1"},
    "elevator": {"level": "plant", "unit": "0/1"},
    "rough_surface": {"level": "plant", "unit": "0/1"},
    # stop level
    "team": {"level": "stop", "unit": "Pers."},
    "speed": {"level": "stop", "unit": "×"},
    "n_plants": {"level": "stop", "unit": ""},
    "total_weight": {"level": "stop", "unit": "kg"},
    "walk_speed": {"level": "stop", "unit": "m/min"},
    "max_crew": {"level": "stop", "unit": "Pers."},
}

PRICE_VARIABLES: dict[str, dict[str, Any]] = {
    "labour_min": {"level": "stop", "unit": "min"},
    "duration_min": {"level": "stop", "unit": "min"},
    "n_plants": {"level": "stop", "unit": ""},
    "total_weight": {"level": "stop", "unit": "kg"},
    "distance_km": {"level": "stop", "unit": "km"},
    "drive_share_km": {"level": "stop", "unit": "km"},
    "distance_surcharge": {"level": "stop", "unit": "€"},
    "base_price": {"level": "stop", "unit": "€"},
    "rate_per_labour_minute": {"level": "stop", "unit": "€/min"},
    "per_plant_fee": {"level": "stop", "unit": "€"},
    "minimum_price": {"level": "stop", "unit": "€"},
    "self_cost": {"level": "stop", "unit": "€"},
    "team": {"level": "stop", "unit": "Pers."},
}

VARIABLES = {"time": TIME_VARIABLES, "price": PRICE_VARIABLES}


def p(value: float, learnable: bool, lo: float, hi: float, unit: str, scale: float) -> dict[str, Any]:
    return {"value": value, "learnable": learnable, "min": lo, "max": hi, "unit": unit, "scale": scale}


DEFAULT_FORMULAS: list[dict[str, Any]] = [
    {
        "key": "time",
        "tier": 1,
        "name": "Startformel (Stufe 1)",
        "description": "Arbeit pro Pflanze aus Gewicht, Weg und Höhenmetern; Dauer pro Stopp aus Teamgröße.",
        "expressions": [
            {
                "name": "work",
                "level": "plant",
                "expr": "(a0 + a1 * weight) * (path_length / walk_speed + k_height * height_meters) * narrow_factor * equipment_factor",
            },
            {
                "name": "duration",
                "level": "stop",
                "expr": "t_fixed + max(sum_plants(work) / team, max_plants(work / crew)) / speed",
            },
        ],
        "parameters": {
            "a0": p(6.0, True, 0.0, 60.0, "", 3.0),
            "a1": p(0.08, True, 0.0, 1.0, "1/kg", 0.04),
            "k_height": p(0.5, True, 0.0, 10.0, "min/m", 0.3),
            "t_fixed": p(10.0, True, 0.0, 60.0, "min", 5.0),
        },
    },
    {
        "key": "time",
        "tier": 2,
        "name": "Erweiterte Formel (Stufe 2)",
        "description": "Wie Stufe 1, zusätzlich feste Handhabungszeit pro Pflanze und Zeit pro Pflanze am Stopp.",
        "expressions": [
            {
                "name": "work",
                "level": "plant",
                "expr": "(a0 + a1 * weight) * (path_length / walk_speed + k_height * height_meters) * narrow_factor * equipment_factor + h0 + h1 * weight",
            },
            {
                "name": "duration",
                "level": "stop",
                "expr": "t_fixed + t_plant * n_plants + max(sum_plants(work) / team, max_plants(work / crew)) / speed",
            },
        ],
        "parameters": {
            "a0": p(5.0, True, 0.0, 60.0, "", 3.0),
            "a1": p(0.07, True, 0.0, 1.0, "1/kg", 0.04),
            "k_height": p(0.45, True, 0.0, 10.0, "min/m", 0.3),
            "t_fixed": p(8.0, True, 0.0, 60.0, "min", 5.0),
            "h0": p(1.0, True, 0.0, 30.0, "min", 1.0),
            "h1": p(0.02, True, 0.0, 1.0, "min/kg", 0.02),
            "t_plant": p(0.5, True, 0.0, 10.0, "min", 0.5),
        },
    },
    {
        "key": "price",
        "tier": 1,
        "name": "Kundenpreis",
        "description": "Grundpreis + Arbeitsminuten + Pflanzen + Entfernungszuschlag, mindestens der Mindestpreis.",
        "expressions": [
            {
                "name": "price",
                "level": "stop",
                "expr": "max(base_price + rate_per_labour_minute * labour_min + per_plant_fee * n_plants + distance_surcharge, minimum_price)",
            },
        ],
        "parameters": {},
    },
]


def seed_formulas(db) -> None:
    from sqlalchemy import select

    from app.models.formulas import Formula, FormulaVersion

    for spec in DEFAULT_FORMULAS:
        exists = db.scalar(
            select(Formula.id).where(
                Formula.tenant_id.is_(None), Formula.key == spec["key"], Formula.tier == spec["tier"]
            )
        )
        if exists:
            continue
        f = Formula(
            tenant_id=None,
            key=spec["key"],
            tier=spec["tier"],
            name=spec["name"],
            description=spec["description"],
        )
        db.add(f)
        db.flush()
        v = FormulaVersion(
            tenant_id=None,
            formula_id=f.id,
            version=1,
            expressions=spec["expressions"],
            parameters=spec["parameters"],
            source="seed",
            note="Standard",
        )
        db.add(v)
        db.flush()
        f.active_version_id = v.id
    db.flush()

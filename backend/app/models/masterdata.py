"""Resources of a nursery: staff, teams, vehicles (with shelves), equipment, availability,
storage areas and the plant species catalog.

Numeric tunables of objects (wage, solo carry weight, speed factors, cost per km …) are settings
with object level (see app/settings/registry.py), not columns, so that the hierarchy
admin -> tenant -> object applies uniformly.
"""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    IdMixin,
    OptionalTenantMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
)

LICENCES = ["B", "BE", "C1", "C1E", "C", "CE"]
# which licence classes include which (a C1E holder may drive B, BE, C1)
LICENCE_INCLUDES = {
    "B": {"B"},
    "BE": {"B", "BE"},
    "C1": {"B", "C1"},
    "C1E": {"B", "BE", "C1", "C1E"},
    "C": {"B", "C1", "C"},
    "CE": {"B", "BE", "C1", "C1E", "C", "CE"},
}


class StaffMember(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "staff_members"

    name: Mapped[str] = mapped_column(String(200), info={"group": "master", "list": True})
    short_name: Mapped[str | None] = mapped_column(String(20), info={"group": "master"})
    phone: Mapped[str | None] = mapped_column(String(60), info={"group": "master"})
    email: Mapped[str | None] = mapped_column(String(200), info={"group": "master"})
    licences: Mapped[list[Any]] = mapped_column(
        default=list, info={"group": "skills", "widget": "tags", "enum_values": LICENCES, "list": True}
    )
    qualifications: Mapped[list[Any]] = mapped_column(
        default=list, info={"group": "skills", "widget": "tags"}
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "master", "list": True})
    color: Mapped[str | None] = mapped_column(String(9), info={"group": "master"})
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})


class Team(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    """A fixed team. The planner may also build teams itself (setting planning.form_teams)."""

    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "list": True})
    member_ids: Mapped[list[Any]] = mapped_column(
        default=list, info={"group": "master", "widget": "staff_multi"}
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"), info={"group": "master", "fk": "vehicle"}
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "master", "list": True})
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})


VEHICLE_KINDS = ["van", "truck", "trailer", "car"]


class Vehicle(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    """Vehicle or trailer. Cargo space is a box; x runs from the front wall to the door (length),
    y from left to right (width), z from the floor up (height)."""

    __tablename__ = "vehicles"

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "list": True})
    plate: Mapped[str | None] = mapped_column(String(20), info={"group": "master", "list": True})
    kind: Mapped[str] = mapped_column(
        String(20), default="van", info={"group": "master", "enum": VEHICLE_KINDS, "list": True}
    )
    required_licence: Mapped[str] = mapped_column(
        String(4), default="B", info={"group": "master", "enum": LICENCES, "list": True}
    )
    seats: Mapped[int] = mapped_column(Integer, default=3, info={"group": "master", "min": 0, "max": 9})
    active: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "master"})
    # cargo space
    cargo_length_cm: Mapped[float] = mapped_column(
        Float, default=340, info={"group": "cargo", "unit": "cm", "list": True}
    )
    cargo_width_cm: Mapped[float] = mapped_column(
        Float, default=175, info={"group": "cargo", "unit": "cm", "list": True}
    )
    cargo_height_cm: Mapped[float] = mapped_column(
        Float, default=185, info={"group": "cargo", "unit": "cm", "list": True}
    )
    payload_kg: Mapped[float] = mapped_column(
        Float, default=1200, info={"group": "cargo", "unit": "kg", "list": True}
    )
    door_width_cm: Mapped[float] = mapped_column(Float, default=155, info={"group": "cargo", "unit": "cm"})
    door_height_cm: Mapped[float] = mapped_column(Float, default=175, info={"group": "cargo", "unit": "cm"})
    door_position: Mapped[str] = mapped_column(
        String(10), default="rear", info={"group": "cargo", "enum": ["rear", "side"]}
    )
    loading_edge_cm: Mapped[float] = mapped_column(Float, default=55, info={"group": "cargo", "unit": "cm"})
    has_ramp: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "cargo"})
    has_lift: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "cargo"})
    # wheel arches as blocked boxes at both side walls
    wheel_arch_x_cm: Mapped[float | None] = mapped_column(Float, info={"group": "cargo", "unit": "cm"})
    wheel_arch_length_cm: Mapped[float | None] = mapped_column(Float, info={"group": "cargo", "unit": "cm"})
    wheel_arch_width_cm: Mapped[float | None] = mapped_column(Float, info={"group": "cargo", "unit": "cm"})
    wheel_arch_height_cm: Mapped[float | None] = mapped_column(Float, info={"group": "cargo", "unit": "cm"})
    # axles (positions measured from the cargo front wall; negative = ahead of it)
    front_axle_x_cm: Mapped[float | None] = mapped_column(Float, info={"group": "axles", "unit": "cm"})
    rear_axle_x_cm: Mapped[float | None] = mapped_column(Float, info={"group": "axles", "unit": "cm"})
    max_front_axle_extra_kg: Mapped[float | None] = mapped_column(
        Float, info={"group": "axles", "unit": "kg"}
    )
    max_rear_axle_extra_kg: Mapped[float | None] = mapped_column(Float, info={"group": "axles", "unit": "kg"})
    # trailers
    max_tongue_load_kg: Mapped[float | None] = mapped_column(Float, info={"group": "trailer", "unit": "kg"})
    min_tongue_load_kg: Mapped[float | None] = mapped_column(Float, info={"group": "trailer", "unit": "kg"})
    hitch_x_cm: Mapped[float | None] = mapped_column(Float, info={"group": "trailer", "unit": "cm"})
    can_tow: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "trailer"})
    max_trailer_kg: Mapped[float | None] = mapped_column(Float, info={"group": "trailer", "unit": "kg"})
    default_trailer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"), info={"group": "trailer", "fk": "vehicle"}
    )
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})


class VehicleShelf(IdMixin, TimestampMixin, TenantMixin, Base):
    """Shelf board in the cargo space: an extra loading level with its own clearance and load limit."""

    __tablename__ = "vehicle_shelves"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), default="Regal")
    x_cm: Mapped[float] = mapped_column(Float, default=0, info={"unit": "cm"})
    y_cm: Mapped[float] = mapped_column(Float, default=0, info={"unit": "cm"})
    length_cm: Mapped[float] = mapped_column(Float, default=120, info={"unit": "cm"})
    depth_cm: Mapped[float] = mapped_column(Float, default=40, info={"unit": "cm"})
    height_cm: Mapped[float] = mapped_column(Float, default=90, info={"unit": "cm"})
    clearance_cm: Mapped[float] = mapped_column(Float, default=60, info={"unit": "cm"})
    max_load_kg: Mapped[float] = mapped_column(Float, default=80, info={"unit": "kg"})
    blocks_floor: Mapped[bool] = mapped_column(Boolean, default=True)


EQUIPMENT_KINDS = [
    "hand_truck",
    "stair_climber",
    "pallet_jack",
    "plant_roller",
    "straps",
    "blanket",
    "ramp",
    "other",
]


class Equipment(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "equipment"

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "list": True})
    kind: Mapped[str] = mapped_column(
        String(20), default="hand_truck", info={"group": "master", "enum": EQUIPMENT_KINDS, "list": True}
    )
    count: Mapped[int] = mapped_column(Integer, default=1, info={"group": "master", "min": 0, "list": True})
    capacity_kg: Mapped[float | None] = mapped_column(
        Float, info={"group": "effect", "unit": "kg", "list": True}
    )
    carry_time_factor: Mapped[float] = mapped_column(
        Float, default=1.0, info={"group": "effect", "unit": "×", "min": 0.1, "max": 3}
    )
    solo_limit_kg: Mapped[float | None] = mapped_column(Float, info={"group": "effect", "unit": "kg"})
    usable_on_stairs: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "effect"})
    surfaces: Mapped[list[Any]] = mapped_column(default=list, info={"group": "effect", "widget": "tags"})
    min_path_width_cm: Mapped[float | None] = mapped_column(Float, info={"group": "effect", "unit": "cm"})
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"), info={"group": "master", "fk": "vehicle"}
    )
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})


AVAILABILITY_KINDS = ["available", "unavailable", "vacation", "sick", "maintenance"]


class Availability(IdMixin, TimestampMixin, TenantMixin, Base):
    """Availability rule of a staff member or vehicle.

    kind 'available' with weekdays = recurring working pattern; other kinds are absences.
    Absences override availability. Without any 'available' rule a resource works on Mon-Fri
    within planning.day_start/day_end.
    """

    __tablename__ = "availability"

    resource_type: Mapped[str] = mapped_column(String(10), info={"enum": ["staff", "vehicle"]})
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(15), default="available", info={"enum": AVAILABILITY_KINDS})
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    weekdays: Mapped[list[Any]] = mapped_column(default=list)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    note: Mapped[str | None] = mapped_column(String(300))


STORAGE_KINDS = ["greenhouse_warm", "greenhouse_cold", "hall", "outdoor_covered", "other"]


class StorageArea(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "storage_areas"

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "list": True})
    kind: Mapped[str] = mapped_column(
        String(20), default="greenhouse_cold", info={"group": "master", "enum": STORAGE_KINDS, "list": True}
    )
    area_m2: Mapped[float] = mapped_column(
        Float, default=100, info={"group": "master", "unit": "m²", "list": True}
    )
    height_cm: Mapped[float] = mapped_column(
        Float, default=300, info={"group": "master", "unit": "cm", "list": True}
    )
    min_temp_c: Mapped[float | None] = mapped_column(Float, info={"group": "master", "unit": "°C"})
    for_frost_sensitive: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "master"})
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})


FROST = ["hardy", "half_hardy", "tender"]
CROWN_SHAPES = ["cylinder", "cone", "sphere", "column", "free"]


class Species(IdMixin, TimestampMixin, SoftDeleteMixin, OptionalTenantMixin, Base):
    """Plant species. Global rows (tenant_id NULL) are maintained by the admin; a tenant can
    override a global species with its own row pointing to it via overrides_id."""

    __tablename__ = "species"
    __table_args__ = (UniqueConstraint("tenant_id", "overrides_id"),)

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "list": True})
    botanical_name: Mapped[str | None] = mapped_column(String(160), info={"group": "master", "list": True})
    aliases: Mapped[list[Any]] = mapped_column(default=list, info={"group": "master", "widget": "tags"})
    crown_shape: Mapped[str] = mapped_column(
        String(10), default="sphere", info={"group": "shape", "enum": CROWN_SHAPES, "list": True}
    )
    crown_density: Mapped[float] = mapped_column(
        Float, default=0.5, info={"group": "shape", "min": 0, "max": 1, "list": True}
    )
    compressibility: Mapped[float] = mapped_column(
        Float, default=0.3, info={"group": "shape", "min": 0, "max": 1}
    )
    soil_kg_per_l: Mapped[float] = mapped_column(
        Float, default=1.3, info={"group": "weight", "unit": "kg/l", "min": 0.2, "max": 2.5}
    )
    plant_kg_per_l: Mapped[float] = mapped_column(
        Float, default=0.03, info={"group": "weight", "unit": "kg/l", "min": 0, "max": 1}
    )
    trunk_kg_per_m: Mapped[float] = mapped_column(
        Float, default=1.5, info={"group": "weight", "unit": "kg/m", "min": 0, "max": 100}
    )
    tip_tendency: Mapped[float] = mapped_column(
        Float, default=0.3, info={"group": "handling", "min": 0, "max": 1}
    )
    frost_sensitivity: Mapped[str] = mapped_column(
        String(12), default="half_hardy", info={"group": "handling", "enum": FROST, "list": True}
    )
    can_tilt: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "handling"})
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "handling"})
    typical_height_cm: Mapped[float | None] = mapped_column(Float, info={"group": "shape", "unit": "cm"})
    overrides_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("species.id", ondelete="CASCADE"), info={"readonly": True}
    )
    notes: Mapped[str | None] = mapped_column(Text, info={"group": "master"})

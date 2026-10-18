"""Customers, addresses, pickup orders, plants, access paths, files/photos, AI drafts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TenantMixin, TimestampMixin
from app.models.masterdata import CROWN_SHAPES


class Counter(TenantMixin, Base):
    """Sequential numbers per tenant (order numbers, plant numbers, invoice numbers)."""

    __tablename__ = "counters"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40))
    value: Mapped[int] = mapped_column(Integer, default=0)


class Customer(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(200), info={"group": "master", "required": True, "list": True})
    company: Mapped[str | None] = mapped_column(String(200), info={"advanced": True, "group": "master"})
    email: Mapped[str | None] = mapped_column(
        String(200), info={"advanced": True, "group": "contact", "list": True}
    )
    phone: Mapped[str | None] = mapped_column(String(60), info={"group": "contact", "list": True})
    preferred_contact: Mapped[str | None] = mapped_column(
        String(10), info={"advanced": True, "group": "contact", "enum": ["phone", "email", "sms", "whatsapp"]}
    )
    consent_photos: Mapped[bool] = mapped_column(
        Boolean, default=False, info={"advanced": True, "group": "privacy"}
    )
    consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"group": "privacy", "readonly": True}
    )
    consent_text: Mapped[str | None] = mapped_column(Text, info={"group": "privacy", "readonly": True})
    notes: Mapped[str | None] = mapped_column(Text, info={"advanced": True, "group": "master"})
    source: Mapped[str] = mapped_column(String(20), default="manual", info={"readonly": True})
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"readonly": True}
    )


class Address(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "addresses"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="CASCADE"),
        index=True,
        info={"fk": "customer", "required": True},
    )
    label: Mapped[str | None] = mapped_column(String(80), info={"advanced": True, "group": "address"})
    street: Mapped[str] = mapped_column(
        String(200), info={"group": "address", "required": True, "list": True}
    )
    postal_code: Mapped[str] = mapped_column(
        String(20), info={"group": "address", "required": True, "list": True}
    )
    city: Mapped[str] = mapped_column(String(120), info={"group": "address", "required": True, "list": True})
    country: Mapped[str] = mapped_column(String(2), default="DE", info={"advanced": True, "group": "address"})
    lat: Mapped[float | None] = mapped_column(Float, info={"group": "geo", "unit": "°"})
    lon: Mapped[float | None] = mapped_column(Float, info={"group": "geo", "unit": "°"})
    geocode_source: Mapped[str | None] = mapped_column(String(20), info={"group": "geo", "readonly": True})
    parking_notes: Mapped[str | None] = mapped_column(Text, info={"group": "hints"})
    bell_notes: Mapped[str | None] = mapped_column(String(200), info={"group": "hints"})
    access_notes: Mapped[str | None] = mapped_column(Text, info={"group": "hints"})


ORDER_STATUS = ["draft", "confirmed", "planned", "picked_up", "stored", "returned", "cancelled"]


class PickupOrder(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    """A pickup (autumn) or return (spring). The return is linked to its pickup and reuses its data."""

    __tablename__ = "pickup_orders"

    number: Mapped[str] = mapped_column(String(30), info={"readonly": True, "list": True})
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="RESTRICT"),
        index=True,
        info={"fk": "customer", "required": True},
    )
    address_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("addresses.id", ondelete="RESTRICT"), info={"fk": "address", "required": True}
    )
    season: Mapped[int] = mapped_column(Integer, info={"group": "order", "list": True, "optional": True})
    direction: Mapped[str] = mapped_column(
        String(10), default="pickup", info={"group": "order", "enum": ["pickup", "return"], "list": True}
    )
    status: Mapped[str] = mapped_column(
        String(15), default="draft", info={"group": "order", "enum": ORDER_STATUS, "list": True}
    )
    earliest_date: Mapped[date | None] = mapped_column(Date, info={"group": "timing"})
    latest_date: Mapped[date | None] = mapped_column(Date, info={"group": "timing"})
    time_windows: Mapped[list[Any]] = mapped_column(
        default=list, info={"group": "timing", "widget": "windows"}
    )
    fixed_date: Mapped[date | None] = mapped_column(Date, info={"group": "timing"})
    priority: Mapped[int] = mapped_column(Integer, default=0, info={"group": "order", "min": 0, "max": 9})
    notes: Mapped[str | None] = mapped_column(Text, info={"advanced": True, "group": "order"})
    source: Mapped[str] = mapped_column(String(20), default="manual", info={"readonly": True})
    return_wish: Mapped[dict[str, Any]] = mapped_column(
        default=dict, info={"hidden": True}
    )  # from the portal
    return_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="SET NULL"), info={"readonly": True}
    )
    price_quoted: Mapped[float | None] = mapped_column(
        Float, info={"readonly": True, "unit": "€", "list": True}
    )
    price_final: Mapped[float | None] = mapped_column(
        Float, info={"module": "customer_billing", "group": "order", "unit": "€"}
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), info={"readonly": True})
    estimate: Mapped[dict[str, Any] | None] = mapped_column(info={"readonly": True, "hidden": True})


class AccessPath(IdMixin, TimestampMixin, TenantMixin, Base):
    """Path from where the plants stand to the vehicle, as a list of segments."""

    __tablename__ = "access_paths"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="Weg")
    length_confirmed_m: Mapped[float | None] = mapped_column(Float, info={"unit": "m"})
    notes: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[dict[str, Any]] = mapped_column(default=dict)


SEGMENT_KINDS = ["flat", "stairs", "ramp", "door", "elevator", "narrow"]
SURFACES = ["paved", "tiles", "wood", "gravel", "lawn", "soil", "other"]


class PathSegment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "path_segments"

    path_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("access_paths.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(10), default="flat", info={"enum": SEGMENT_KINDS})
    length_m: Mapped[float] = mapped_column(Float, default=5, info={"unit": "m"})
    steps: Mapped[int] = mapped_column(Integer, default=0)
    height_diff_m: Mapped[float] = mapped_column(Float, default=0, info={"unit": "m"})
    min_width_cm: Mapped[float | None] = mapped_column(Float, info={"unit": "cm"})
    doors: Mapped[int] = mapped_column(Integer, default=0)
    surface: Mapped[str] = mapped_column(String(10), default="paved", info={"enum": SURFACES})
    slope_pct: Mapped[float] = mapped_column(Float, default=0, info={"unit": "%"})
    elevator: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(300))


POT_MATERIALS = ["plastic", "terracotta", "glazed", "wood", "metal", "stone", "fiberglass", "concrete"]
PLANT_STATUS = ["registered", "picked_up", "stored", "returned", "missing"]


class Plant(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "plants"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True, info={"readonly": True}
    )
    number: Mapped[int] = mapped_column(Integer, info={"readonly": True, "list": True, "optional": True})
    label: Mapped[str | None] = mapped_column(String(120), info={"group": "master", "list": True})
    # species as named by the AI or a person; the properties below are stored on the plant itself
    species_name: Mapped[str | None] = mapped_column(String(160), info={"group": "master", "list": True})
    # link into the internal knowledge base (admin only), set when the name matches an entry
    species_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("species.id", ondelete="SET NULL"), info={"readonly": True}
    )
    species_source: Mapped[str | None] = mapped_column(
        String(20), info={"readonly": True, "enum": ["ai", "knowledge", "person", "migrated"]}
    )
    access_path_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("access_paths.id", ondelete="SET NULL"), info={"group": "master"}
    )
    quantity_note: Mapped[str | None] = mapped_column(String(120), info={"hidden": True})
    # pot
    pot_shape: Mapped[str] = mapped_column(
        String(10), default="round", info={"group": "pot", "enum": ["round", "square"]}
    )
    pot_diameter_cm: Mapped[float | None] = mapped_column(
        Float, info={"group": "pot", "unit": "cm", "list": True}
    )
    pot_length_cm: Mapped[float | None] = mapped_column(Float, info={"group": "pot", "unit": "cm"})
    pot_width_cm: Mapped[float | None] = mapped_column(Float, info={"group": "pot", "unit": "cm"})
    pot_height_cm: Mapped[float | None] = mapped_column(Float, info={"group": "pot", "unit": "cm"})
    pot_material: Mapped[str | None] = mapped_column(String(12), info={"group": "pot", "enum": POT_MATERIALS})
    # crown
    crown_shape: Mapped[str | None] = mapped_column(String(10), info={"group": "crown", "enum": CROWN_SHAPES})
    crown_height_cm: Mapped[float | None] = mapped_column(Float, info={"group": "crown", "unit": "cm"})
    crown_width_cm: Mapped[float | None] = mapped_column(
        Float, info={"group": "crown", "unit": "cm", "list": True}
    )
    crown_start_cm: Mapped[float | None] = mapped_column(Float, info={"group": "crown", "unit": "cm"})
    crown_density: Mapped[float | None] = mapped_column(Float, info={"group": "crown", "min": 0, "max": 1})
    compressibility: Mapped[float | None] = mapped_column(Float, info={"group": "crown", "min": 0, "max": 1})
    total_height_cm: Mapped[float | None] = mapped_column(
        Float, info={"group": "crown", "unit": "cm", "list": True}
    )
    # weight
    weight_kg: Mapped[float | None] = mapped_column(
        Float, info={"group": "weight", "unit": "kg", "list": True}
    )
    weight_uncertainty_kg: Mapped[float | None] = mapped_column(
        Float, info={"advanced": True, "group": "weight", "unit": "kg"}
    )
    weight_measured_kg: Mapped[float | None] = mapped_column(Float, info={"group": "weight", "unit": "kg"})
    # weight model coefficients (from the AI or the knowledge base)
    soil_kg_per_l: Mapped[float | None] = mapped_column(
        Float, info={"advanced": True, "group": "weight", "unit": "kg/l", "min": 0.2, "max": 2.5}
    )
    plant_kg_per_l: Mapped[float | None] = mapped_column(
        Float, info={"advanced": True, "group": "weight", "unit": "kg/l", "min": 0, "max": 1}
    )
    trunk_kg_per_m: Mapped[float | None] = mapped_column(
        Float, info={"advanced": True, "group": "weight", "unit": "kg/m", "min": 0, "max": 100}
    )
    # handling
    can_tilt: Mapped[bool | None] = mapped_column(Boolean, info={"group": "handling"})
    tip_tendency: Mapped[float | None] = mapped_column(Float, info={"group": "handling", "min": 0, "max": 1})
    must_secure: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "handling"})
    sensitive: Mapped[bool | None] = mapped_column(Boolean, info={"group": "handling"})
    frost_sensitive: Mapped[bool | None] = mapped_column(Boolean, info={"group": "handling"})
    not_stackable: Mapped[bool] = mapped_column(
        Boolean, default=True, info={"advanced": True, "group": "handling"}
    )
    team_size_override: Mapped[int | None] = mapped_column(
        Integer, info={"advanced": True, "group": "handling", "min": 1, "max": 8}
    )
    required_equipment: Mapped[list[Any]] = mapped_column(
        default=list, info={"advanced": True, "group": "handling", "widget": "tags"}
    )
    incompatible_with: Mapped[list[Any]] = mapped_column(default=list, info={"hidden": True})
    # bookkeeping
    status: Mapped[str] = mapped_column(
        String(12), default="registered", info={"enum": PLANT_STATUS, "readonly": True, "list": True}
    )
    storage_area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("storage_areas.id", ondelete="SET NULL"),
        info={"module": "storage", "group": "master", "fk": "storage_area"},
    )
    qr_code: Mapped[str | None] = mapped_column(String(64), index=True, info={"readonly": True})
    estimated_fields: Mapped[list[Any]] = mapped_column(default=list, info={"readonly": True})
    field_confidence: Mapped[dict[str, Any]] = mapped_column(default=dict, info={"readonly": True})
    notes: Mapped[str | None] = mapped_column(Text, info={"advanced": True, "group": "master"})


class StoredFile(IdMixin, TenantMixin, Base):
    """A file in the StorageBackend (photos, PDFs). Content is never stored in the database."""

    __tablename__ = "stored_files"

    key: Mapped[str] = mapped_column(String(300), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(30), default="photo")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delete_after: Mapped[date | None] = mapped_column(Date)


PHOTO_KINDS = [
    "plant_front",
    "plant_side",
    "plant_top",
    "pot",
    "path_start",
    "path_segment",
    "path_end",
    "pickup_proof",
    "delivery_proof",
    "damage",
    "other",
]


class Photo(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "photos"

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stored_files.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(15), default="other", info={"enum": PHOTO_KINDS})
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    plant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("plants.id", ondelete="CASCADE"), index=True
    )
    path_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("access_paths.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("path_segments.id", ondelete="SET NULL")
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    stop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[dict[str, Any]] = mapped_column(default=dict)
    a4_detected: Mapped[bool | None] = mapped_column(Boolean)
    a4: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ai_results: Mapped[dict[str, Any]] = mapped_column(default=dict)
    caption: Mapped[str | None] = mapped_column(String(300))
    client_id: Mapped[str | None] = mapped_column(
        String(64), index=True
    )  # offline upload from the driver app


DRAFT_STATUS = ["new", "processing", "review", "confirmed", "rejected", "failed"]


class Draft(IdMixin, TimestampMixin, TenantMixin, Base):
    """AI intake: a forwarded message becomes a draft for customer, order, plants and path.
    Nothing becomes a real record before a human confirms it."""

    __tablename__ = "drafts"

    status: Mapped[str] = mapped_column(String(12), default="new", info={"enum": DRAFT_STATUS})
    source_kind: Mapped[str] = mapped_column(
        String(12), default="text", info={"enum": ["text", "email", "voice", "agent", "form"]}
    )
    source_text: Mapped[str] = mapped_column(Text, default="")
    extracted: Mapped[dict[str, Any]] = mapped_column(default=dict)
    confidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    review_fields: Mapped[list[Any]] = mapped_column(default=list)
    photo_check: Mapped[dict[str, Any]] = mapped_column(default=dict)
    follow_up: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_via: Mapped[str] = mapped_column(String(20), default="ui")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error: Mapped[str | None] = mapped_column(Text)

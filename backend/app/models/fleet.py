"""Modular vehicles (package C): reusable modules (shelf, fixture) assigned to several vehicles, and
vehicle drafts that the AI builds from cargo-space photos or a chat and a person confirms."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TenantMixin, TimestampMixin

MODULE_KINDS = ["shelf", "fixture"]


class VehicleModule(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    """A shelf (extra loading level) or a fixture (blocked box, e.g. a tool box or a ramp holder).

    Position in the cargo space: x from the front wall, y from the left wall, both in cm. The same
    module can be assigned to several vehicles of the same build."""

    __tablename__ = "vehicle_modules"

    name: Mapped[str] = mapped_column(String(120), info={"group": "master", "required": True, "list": True})
    kind: Mapped[str] = mapped_column(
        String(10), default="shelf", info={"group": "master", "enum": MODULE_KINDS, "list": True}
    )
    x_cm: Mapped[float] = mapped_column(Float, default=0, info={"group": "geometry", "unit": "cm"})
    y_cm: Mapped[float] = mapped_column(Float, default=0, info={"group": "geometry", "unit": "cm"})
    length_cm: Mapped[float] = mapped_column(
        Float, default=120, info={"group": "geometry", "unit": "cm", "list": True}
    )
    depth_cm: Mapped[float] = mapped_column(
        Float, default=40, info={"group": "geometry", "unit": "cm", "list": True}
    )
    height_cm: Mapped[float] = mapped_column(
        Float, default=90, info={"group": "geometry", "unit": "cm", "list": True}
    )
    # shelves only: free height above the board and load limit
    clearance_cm: Mapped[float | None] = mapped_column(Float, info={"group": "shelf", "unit": "cm"})
    max_load_kg: Mapped[float | None] = mapped_column(Float, info={"group": "shelf", "unit": "kg"})
    blocks_floor: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "shelf"})
    # own weight reduces the payload of the vehicle
    weight_kg: Mapped[float] = mapped_column(Float, default=0, info={"group": "geometry", "unit": "kg"})
    notes: Mapped[str | None] = mapped_column(Text, info={"advanced": True, "group": "master"})


class VehicleModuleLink(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "vehicle_module_links"
    __table_args__ = (UniqueConstraint("vehicle_id", "module_id"),)

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vehicle_modules.id", ondelete="CASCADE"), index=True
    )


DRAFT_STATES = ["open", "confirmed", "discarded"]


class VehicleDraft(IdMixin, TimestampMixin, TenantMixin, Base):
    """AI result for a vehicle: every value with a confidence; nothing changes before a person confirms.

    vehicle_id set = proposed changes to that vehicle (chat), otherwise a new vehicle."""

    __tablename__ = "vehicle_drafts"

    status: Mapped[str] = mapped_column(String(10), default="open")
    source: Mapped[str] = mapped_column(String(10), default="chat")  # chat | photo
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(
        default=dict
    )  # {vehicle: {...vf}, shelves: [...], costs: {...}}
    messages: Mapped[list[Any]] = mapped_column(default=list)  # chat history [{role, text, at}]
    questions: Mapped[list[Any]] = mapped_column(default=list)
    review_fields: Mapped[list[Any]] = mapped_column(default=list)
    photo_file_ids: Mapped[list[Any]] = mapped_column(default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

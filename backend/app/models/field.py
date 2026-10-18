"""Field data from the driver app: time events, measurements per stop, deviation reports."""

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

from app.models.base import Base, IdMixin, TenantMixin, TimestampMixin

EVENT_KINDS = [
    "shift_start",  # day starts at the depot
    "depart",  # trip leaves the depot
    "arrive",  # 1. arrival at the customer
    "carry_start",  # 2. carrying begins
    "plant_done",  # 3. (optional) one plant is in the vehicle
    "loaded",  # 4. everything loaded, with mandatory photo (pickup)
    "delivered",  # 4. everything set down at the customer, with photo (spring return)
    "leave",  # 5. drive on
    "break_start",
    "break_end",
    "unload",  # back at the depot, unloading
    "shift_end",
    "qr_scan",  # QR module: plant scanned at its place in the vehicle
]

DEVIATION_KINDS = ["plant_bigger", "plant_heavier", "path_different", "customer_absent", "damage", "other"]


class TourEvent(IdMixin, TenantMixin, Base):
    """One button press in the driver app. client_id makes offline sync idempotent."""

    __tablename__ = "tour_events"
    __table_args__ = (UniqueConstraint("tenant_id", "client_id", name="uq_tour_events_client"),)

    client_id: Mapped[str] = mapped_column(String(64))
    tour_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    stop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    plant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


class Measurement(IdMixin, TimestampMixin, TenantMixin, Base):
    """Measured on-site duration of one stop (and optionally per plant), the input of model fitting."""

    __tablename__ = "measurements"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    tour_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tours.id", ondelete="SET NULL"))
    stop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(12), default="app")  # app | manual | demo | synthetic
    team_size: Mapped[int] = mapped_column(Integer)
    member_ids: Mapped[list[Any]] = mapped_column(default=list)
    drive_min: Mapped[float | None] = mapped_column(Float)
    fixed_min: Mapped[float | None] = mapped_column(Float)  # arrival -> carrying begins
    carry_min: Mapped[float | None] = mapped_column(Float)  # carrying begins -> loaded
    duration_min: Mapped[float] = mapped_column(Float)  # on site (without breaks): what the formula predicts
    break_min: Mapped[float] = mapped_column(Float, default=0)
    per_plant: Mapped[list[Any]] = mapped_column(default=list)  # [{"plant_id", "minutes"}]
    predicted_min: Mapped[float | None] = mapped_column(Float)
    experiment: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[str | None] = mapped_column(String(200))
    features: Mapped[dict[str, Any]] = mapped_column(default=dict)
    deviations: Mapped[int] = mapped_column(Integer, default=0)


class Deviation(IdMixin, TimestampMixin, TenantMixin, Base):
    """Report from the field: plant bigger/heavier, path different, customer absent, damage."""

    __tablename__ = "deviations"
    __table_args__ = (UniqueConstraint("tenant_id", "client_id", name="uq_deviations_client"),)

    client_id: Mapped[str] = mapped_column(String(64))
    tour_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tours.id", ondelete="SET NULL"))
    stop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    plant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("plants.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    values: Mapped[dict[str, Any]] = mapped_column(default=dict)
    photo_ids: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | applied | dismissed
    reported_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

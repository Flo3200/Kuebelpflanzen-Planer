"""Plans, tours (one trip of a vehicle/team on a day) and stops."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, TimestampMixin

PLAN_STATUS = ["draft", "computing", "ready", "failed", "archived"]


class Plan(IdMixin, TimestampMixin, TenantMixin, Base):
    """Result of one planning run. Scenario plans point to their base plan."""

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(160))
    season: Mapped[int | None] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(10), default="pickup")
    start_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(12), default="plan")  # plan | scenario
    parent_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    scenario: Mapped[dict[str, Any]] = mapped_column(default=dict)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    kpis: Mapped[dict[str, Any]] = mapped_column(default=dict)
    unassigned: Mapped[list[Any]] = mapped_column(default=list)
    units: Mapped[list[Any]] = mapped_column(default=list)
    solver: Mapped[dict[str, Any]] = mapped_column(default=dict)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tour(IdMixin, TimestampMixin, TenantMixin, Base):
    """One trip of a vehicle (with team) from the depot and back. Several trips per day possible."""

    __tablename__ = "tours"

    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    unit_key: Mapped[str] = mapped_column(String(120))
    trip_no: Mapped[int] = mapped_column(Integer, default=1)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"))
    trailer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vehicles.id", ondelete="SET NULL"))
    member_ids: Mapped[list[Any]] = mapped_column(default=list)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(160), default="")
    color: Mapped[str] = mapped_column(String(9), default="#2b5139")
    start_min: Mapped[int] = mapped_column(Integer, default=0)  # minutes after midnight
    end_min: Mapped[int] = mapped_column(Integer, default=0)
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    drive_min: Mapped[float] = mapped_column(Float, default=0)
    service_min: Mapped[float] = mapped_column(Float, default=0)
    load: Mapped[dict[str, Any]] = mapped_column(default=dict)
    costs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    breaks: Mapped[list[Any]] = mapped_column(default=list)
    unit: Mapped[dict[str, Any]] = mapped_column(default=dict)
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="planned")  # planned | in_progress | done
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    load_status: Mapped[str] = mapped_column(String(12), default="unknown")  # unknown | ok | failed
    load_message: Mapped[str | None] = mapped_column(Text)
    # package F: depot window after the trip (pickup: unloading; return: loading before the trip)
    depot_start_min: Mapped[int | None] = mapped_column(Integer)
    depot_end_min: Mapped[int | None] = mapped_column(Integer)
    unload_min: Mapped[float | None] = mapped_column(Float)


class TourStop(IdMixin, TenantMixin, Base):
    __tablename__ = "tour_stops"

    tour_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    arrival_min: Mapped[int] = mapped_column(Integer, default=0)
    start_min: Mapped[int] = mapped_column(Integer, default=0)
    end_min: Mapped[int] = mapped_column(Integer, default=0)
    service_min: Mapped[float] = mapped_column(Float, default=0)
    predicted_min: Mapped[float] = mapped_column(Float, default=0)
    team_size: Mapped[int] = mapped_column(Integer, default=1)
    drive_from_prev_min: Mapped[float] = mapped_column(Float, default=0)
    distance_from_prev_km: Mapped[float] = mapped_column(Float, default=0)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    experiment: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(12), default="planned"
    )  # planned | arrived | carrying | loaded | delivered | done | skipped
    costs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    warnings: Mapped[list[Any]] = mapped_column(default=list)

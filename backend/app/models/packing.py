"""Load plans of tours: one per cargo space, with the placement of every plant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin


class LoadPlan(IdMixin, TenantMixin, Base):
    __tablename__ = "load_plans"

    tour_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text)
    spaces: Mapped[list[Any]] = mapped_column(default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    violations: Mapped[list[Any]] = mapped_column(default=list)
    unplaced: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoadPlacement(IdMixin, TenantMixin, Base):
    __tablename__ = "load_placements"

    load_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("load_plans.id", ondelete="CASCADE"), index=True
    )
    plant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plants.id", ondelete="CASCADE"))
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    stop_position: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    space_id: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(60), default="floor")
    orientation: Mapped[str] = mapped_column(String(12), default="upright")
    angle: Mapped[float] = mapped_column(Float, default=0)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    dims: Mapped[dict[str, Any]] = mapped_column(default=dict)
    instruction: Mapped[str] = mapped_column(Text, default="")
    secure: Mapped[bool] = mapped_column(Boolean, default=False)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

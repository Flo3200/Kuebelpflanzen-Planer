"""Formulas with versions and tiers, model fits, quotes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, OptionalTenantMixin, TenantMixin, TimestampMixin


class Formula(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    """A formula family (key: time | price) in one tier. Global (admin) or tenant override."""

    __tablename__ = "formulas"

    key: Mapped[str] = mapped_column(String(30), index=True)
    tier: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    overrides_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("formulas.id", ondelete="CASCADE")
    )


class FormulaVersion(IdMixin, OptionalTenantMixin, Base):
    """Immutable version: named expressions (plant or stop level) and parameters.

    expressions: [{"name": "work", "level": "plant", "expr": "..."}, ...]
    parameters:  {"a0": {"value": 6, "learnable": true, "min": 0, "max": 50, "unit": "", "scale": 3}, ...}
    """

    __tablename__ = "formula_versions"

    formula_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("formulas.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    expressions: Mapped[list[Any]] = mapped_column(default=list)
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | fit | seed
    fit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelFit(IdMixin, TenantMixin, Base):
    """Result of fitting learnable parameters to measurements (phase 6)."""

    __tablename__ = "model_fits"

    formula_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("formulas.id", ondelete="CASCADE"))
    base_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(
        String(15), default="proposed"
    )  # proposed | adopted | discarded | rejected
    n_measurements: Mapped[int] = mapped_column(Integer, default=0)
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    staff_factors: Mapped[dict[str, Any]] = mapped_column(default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Quote(IdMixin, TimestampMixin, TenantMixin, Base):
    """Offer to a customer (PDF). Amounts are frozen at creation."""

    __tablename__ = "quotes"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(30))
    net_eur: Mapped[float] = mapped_column(Float)
    vat_pct: Mapped[float] = mapped_column(Float)
    gross_eur: Mapped[float] = mapped_column(Float)
    lines: Mapped[list[Any]] = mapped_column(default=list)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(15), default="created")
    with_drive_estimate: Mapped[bool] = mapped_column(Boolean, default=True)

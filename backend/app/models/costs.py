"""Own cost items of a tenant (package E): a named amount with a basis, for the whole nursery or for
one vehicle or one staff member (vehicle modules follow in package C)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TenantMixin, TimestampMixin

# per_km: driven km · per_hour: hours on tour · per_use: per trip · per_day: per day in use ·
# per_month: monthly amount, pro rata per day in use · per_plant: per plant transported
COST_BASES = ["per_km", "per_hour", "per_use", "per_day", "per_month", "per_plant"]


class CostItem(IdMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, Base):
    __tablename__ = "cost_items"

    name: Mapped[str] = mapped_column(String(160), info={"group": "master", "required": True, "list": True})
    amount_eur: Mapped[float] = mapped_column(
        Float, default=0, info={"group": "master", "unit": "€", "min": 0, "list": True}
    )
    basis: Mapped[str] = mapped_column(
        String(12), default="per_day", info={"group": "master", "enum": COST_BASES, "list": True}
    )
    # what the item belongs to; none of them = the whole nursery
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        index=True,
        info={"group": "scope", "fk": "vehicle"},
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        index=True,
        info={"group": "scope", "fk": "staff"},
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, info={"group": "master", "list": True})
    notes: Mapped[str | None] = mapped_column(Text, info={"advanced": True, "group": "master"})

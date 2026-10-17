"""Declarative base and mixins shared by all models.

Row-level security mode per table is declared with the class attribute ``__rls__``:
  "strict" – rows belong to exactly one tenant (tenant_id may be NULL for platform rows,
             which are then only visible with bypass)
  "shared" – tenant_id NULL marks a global row, readable by every tenant, writable only by admin
  None     – global platform table without tenant_id
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}

    __rls__: str | None = None


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), info={"readonly": True}
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), info={"readonly": True}
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, info={"hidden": True}
    )


class TenantMixin:
    __rls__ = "strict"

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, info={"hidden": True}
        )


class OptionalTenantMixin:
    """tenant_id NULL = global (platform) row."""

    __rls__ = "shared"

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            Uuid,
            ForeignKey("tenants.id", ondelete="CASCADE"),
            index=True,
            nullable=True,
            info={"hidden": True},
        )


def rls_tables() -> dict[str, str]:
    """Map table name -> RLS mode for all mapped classes."""
    out: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        mode = getattr(cls, "__rls__", None)
        if mode and hasattr(cls, "__tablename__"):
            out[cls.__tablename__] = mode
    return out

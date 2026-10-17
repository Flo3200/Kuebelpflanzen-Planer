"""Simple counts for dashboards."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import Base

COUNTED = ("users", "staff_members", "vehicles", "customers", "pickup_orders", "plants", "drafts", "tours")


def tenant_counts(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in COUNTED:
        table = Base.metadata.tables.get(name)
        if table is None or "tenant_id" not in table.c:
            continue
        stmt = select(func.count()).select_from(table).where(table.c.tenant_id == tenant_id)
        if "deleted_at" in table.c:
            stmt = stmt.where(table.c.deleted_at.is_(None))
        out[name] = db.scalar(stmt) or 0
    return out

"""Monthly platform invoices (periodic job of the platform, first days of a month)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select

from app.billing.service import create_platform_invoice, previous_month
from app.core.errors import Conflict
from app.jobs.queue import JobContext, handler
from app.jobs.worker import periodic
from app.models.core import Tenant


@handler("billing.monthly_invoices")
def monthly_invoices(ctx: JobContext) -> dict:
    period = ctx.payload.get("period")
    if period:
        y, m = (int(x) for x in period.split("-"))
        start, end = previous_month(date(y, m, 1))
    else:
        start, end = previous_month()
    created, skipped = [], 0
    tenants = list(
        ctx.db.scalars(select(Tenant).where(Tenant.deleted_at.is_(None), Tenant.status == "active"))
    )
    for i, t in enumerate(tenants):
        ctx.progress(i / max(1, len(tenants)), f"Rechnung {i + 1} von {len(tenants)}")
        if ctx.payload.get("tenant_id") and str(t.id) != ctx.payload["tenant_id"]:
            continue
        try:
            inv = create_platform_invoice(ctx.db, ctx.actor, t, start, end)
        except Conflict:
            skipped += 1
            continue
        if inv is not None:
            created.append(inv.number)
    return {"period": f"{start:%Y-%m}", "created": created, "skipped": skipped}


@periodic("billing.monthly_invoices")
def due(db, tenant_id: uuid.UUID | None, now: datetime) -> str | None:
    """Once per month for the whole platform (the key is the month that is billed + 1)."""
    if tenant_id is not None:
        return None
    return f"{now.year}-{now.month:02d}"

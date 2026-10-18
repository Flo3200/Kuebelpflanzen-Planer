"""Billing: platform invoices to tenants (admin), usage overview (tenant and admin), invoices of a
tenant to its own customers (optional)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.confirm import confirm_if_agent
from app.api.deps import DB, CurrentActor
from app.billing.service import (
    cancel_invoice,
    create_customer_invoice,
    create_platform_invoice,
    invoice_dict,
    month_bounds,
    preview_platform_invoice,
    usage_overview,
)
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.core.modules import require_module
from app.jobs.queue import enqueue, run_now
from app.models.core import Tenant
from app.models.orders import PickupOrder, StoredFile
from app.models.platform import Invoice
from app.storage.backend import get_storage

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _tenant_for(db, actor: Actor, tenant_id: uuid.UUID | None) -> Tenant:
    """Admins name a tenant; a tenant user always gets its own."""
    if actor.tenant_id is not None:
        actor.require("tenant.billing")
        tid = actor.tenant_id
    else:
        actor.require("platform.billing")
        if tenant_id is None:
            raise AppError("errors.tenant_required")
        tid = tenant_id
    t = db.get(Tenant, tid)
    if t is None:
        raise NotFound()
    return t


def _period(year: int | None, month: int | None) -> tuple[date, date]:
    today = date.today()
    return month_bounds(year or today.year, month or today.month)


@router.get("/usage")
def usage(
    actor: CurrentActor,
    db: DB,
    tenant_id: uuid.UUID | None = None,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Usage overview of one month (AI, plants) with the invoice preview."""
    t = _tenant_for(db, actor, tenant_id)
    start, end = _period(year, month)
    return {
        **usage_overview(db, t.id, start, end),
        "preview": preview_platform_invoice(db, t, start, end),
        "tenant": {"id": t.id, "name": t.name},
    }


@router.get("/invoices")
def list_invoices(
    actor: CurrentActor, db: DB, tenant_id: uuid.UUID | None = None, kind: str = "platform"
) -> list[dict[str, Any]]:
    q = select(Invoice).where(Invoice.kind == kind)
    if actor.tenant_id is not None:
        actor.require("tenant.billing" if kind == "platform" else "orders.read")
        if kind != "platform":
            require_module(db, actor.tenant_id, "customer_billing")
        q = q.where(Invoice.tenant_id == actor.tenant_id)
    else:
        actor.require("platform.billing")
        if tenant_id:
            q = q.where(Invoice.tenant_id == tenant_id)
    return [
        invoice_dict(i)
        for i in db.scalars(q.order_by(Invoice.issue_date.desc(), Invoice.number.desc()).limit(500))
    ]


def _invoice(db, actor: Actor, invoice_id: uuid.UUID) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or (actor.tenant_id is not None and inv.tenant_id != actor.tenant_id):
        raise NotFound()
    if actor.tenant_id is None:
        actor.require("platform.billing")
    elif inv.kind == "platform":
        actor.require("tenant.billing")
    else:
        actor.require("orders.read")
    return inv


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: uuid.UUID, actor: CurrentActor, db: DB) -> Response:
    inv = _invoice(db, actor, invoice_id)
    f = db.get(StoredFile, inv.file_id) if inv.file_id else None
    if f is None:
        raise NotFound()
    return Response(
        get_storage().get(f.key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{f.filename}"'},
    )


class CreateIn(BaseModel):
    tenant_id: uuid.UUID
    year: int
    month: int
    allow_empty: bool = False


@router.post("/invoices", status_code=201)
def create(data: CreateIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Admin: platform invoice for one tenant and month (normally done by the monthly job)."""
    actor.require("platform.billing")
    confirm_if_agent(
        db,
        actor,
        "billing:create_invoice",
        {"tenant_id": str(data.tenant_id), "year": data.year, "month": data.month},
    )
    t = db.get(Tenant, data.tenant_id)
    if t is None:
        raise NotFound()
    start, end = month_bounds(data.year, data.month)
    inv = create_platform_invoice(db, actor, t, start, end, allow_empty=data.allow_empty)
    if inv is None:
        raise AppError("errors.invoice_empty")
    return invoice_dict(inv)


class RunIn(BaseModel):
    year: int | None = None
    month: int | None = None
    sync: bool = False


@router.post("/run-monthly")
def run_monthly(data: RunIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Admin: start the monthly invoice run now (for the month before the given one)."""
    actor.require("platform.billing")
    confirm_if_agent(db, actor, "billing:run_monthly", {"year": data.year, "month": data.month})
    payload = {"period": f"{data.year}-{data.month:02d}"} if data.year and data.month else {}
    job = enqueue(
        db, "billing.monthly_invoices", {**payload, "manual": True}, tenant_id=None, created_by=actor.user_id
    )
    if data.sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result, "error": job.error}


@router.post("/invoices/{invoice_id}/cancel")
def cancel(invoice_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    inv = _invoice(db, actor, invoice_id)
    if inv.kind == "platform":
        actor.require("platform.billing")
    else:
        actor.require("orders.write")
    confirm_if_agent(db, actor, "billing:cancel_invoice", {"id": str(invoice_id)})
    return invoice_dict(cancel_invoice(db, actor, inv))


@router.post("/invoices/{invoice_id}/paid")
def mark_paid(invoice_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    inv = _invoice(db, actor, invoice_id)
    actor.require("platform.billing" if inv.kind == "platform" else "orders.write")
    confirm_if_agent(db, actor, "billing:mark_paid", {"id": str(invoice_id)})
    inv.status = "paid"
    inv.paid_at = datetime.now(UTC)
    audit.record(db, actor, tenant_id=inv.tenant_id, entity="invoice", entity_id=inv.id, action="paid")
    return invoice_dict(inv)


@router.post("/orders/{order_id}/invoice", status_code=201)
def order_invoice(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Tenant: invoice to its own customer for an order (optional module of the tenant)."""
    actor.require("orders.write")
    order = db.get(PickupOrder, order_id)
    if order is None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    require_module(db, order.tenant_id, "customer_billing")
    confirm_if_agent(db, actor, "billing:customer_invoice", {"order_id": str(order_id)})
    open_inv = db.scalar(
        select(Invoice).where(
            Invoice.order_id == order.id,
            Invoice.kind == "customer",
            Invoice.status != "cancelled",
            Invoice.cancels_id.is_(None),
        )
    )
    if open_inv is not None:
        raise AppError("errors.invoice_exists", status_code=409, number=open_inv.number)
    return invoice_dict(create_customer_invoice(db, actor, order))

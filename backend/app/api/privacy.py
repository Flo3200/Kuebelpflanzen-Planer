"""Privacy: export and erasure of a customer's data on request; retention run."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.agents.confirm import confirm_if_agent
from app.api.deps import DB, CurrentActor
from app.core.errors import AppError, NotFound
from app.jobs.queue import enqueue, run_now
from app.models.orders import Customer
from app.privacy.service import erase_customer, export_customer

router = APIRouter(tags=["privacy"])


def _customer(db, actor, customer_id: uuid.UUID) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None or c.tenant_id != actor.tenant_id:
        raise NotFound()
    return c


@router.get("/api/customers/{customer_id}/export")
def export(customer_id: uuid.UUID, actor: CurrentActor, db: DB) -> Response:
    """All data of a customer as ZIP (data.json, photos, offers, invoices)."""
    actor.require("customers.read")
    c = _customer(db, actor, customer_id)
    data = export_customer(db, actor, c)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="kunde-{c.id}.zip"'},
    )


class EraseIn(BaseModel):
    confirm: bool


@router.post("/api/customers/{customer_id}/erase")
def erase(customer_id: uuid.UUID, data: EraseIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Erase the personal data of a customer (invoices stay because of the retention obligation)."""
    actor.require("customers.write")
    if not data.confirm:
        raise AppError("errors.confirm_required")
    c = _customer(db, actor, customer_id)
    confirm_if_agent(db, actor, "delete:customer_data", {"id": str(customer_id)})
    return {"ok": True, "erased": erase_customer(db, actor, c)}


class RetentionIn(BaseModel):
    sync: bool = False


@router.post("/api/privacy/retention")
def retention(data: RetentionIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Run the automatic deletion of the tenant now (normally daily)."""
    actor.require("tenant.settings")
    tid = actor.require_tenant()
    confirm_if_agent(db, actor, "delete:retention", {"tenant_id": str(tid)})
    job = enqueue(
        db,
        "privacy.retention",
        {"tenant_id": str(tid), "manual": True},
        tenant_id=tid,
        created_by=actor.user_id,
    )
    if data.sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result, "error": job.error}


@router.get("/api/privacy/overview")
def privacy_overview(actor: CurrentActor, db: DB) -> dict[str, Any]:
    """What personal data is stored and when it is deleted."""
    actor.require("customers.read")
    from app.privacy.service import overview

    return overview(db, actor.require_tenant())


@router.post("/api/privacy/remove-contacts")
def remove_contacts(actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Remove phone and e-mail of all customers of the tenant."""
    actor.require("tenant.settings")
    tid = actor.require_tenant()
    confirm_if_agent(db, actor, "delete:contacts", {"tenant_id": str(tid)})
    from app.privacy.service import remove_contact_data

    return {"customers": remove_contact_data(db, actor, tid)}

"""Customer portal API (/api/portal/*): own orders with status and appointment, consent, guided photo
upload, location, offers (view, accept), spring return wish, online payment. A customer login can only
reach these paths (see app.api.deps.CUSTOMER_PATHS) and only its own data."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentActor
from app.api.files import IMAGE_TYPES, photo_dict, save_photo
from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.db import system_session
from app.core.errors import AppError, Forbidden, NotFound
from app.core.modules import module_enabled, module_states, require_module
from app.jobs.queue import enqueue
from app.models.core import Tenant
from app.models.formulas import Quote
from app.models.masterdata import Species
from app.models.orders import Address, Customer, Photo, PickupOrder, Plant
from app.models.platform import Invoice, Payment
from app.payments.providers import provider_for, verify_stripe_signature
from app.portal.service import (
    already_paid,
    appointment,
    customer_orders,
    mark_paid,
    open_amount,
    own_order,
    payment_dict,
    portal_link,
    progress,
    tenant_contact,
)
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import geometry

router = APIRouter(tags=["portal"])
public_router = APIRouter(tags=["payments"])

GUIDED_PLANT = ["plant_front", "plant_side", "plant_top", "pot"]
GUIDED_PATH = ["path_start", "path_segment", "path_end"]


def _customer(actor: Actor, db: Session) -> uuid.UUID:
    actor.require("customer.portal")
    if actor.customer_id is None:
        raise Forbidden()
    require_module(db, actor.tenant_id, "portal")
    return actor.customer_id


@router.get("/api/portal/me")
def me(actor: CurrentActor, db: DB) -> dict[str, Any]:
    cid = _customer(actor, db)
    c = db.get(Customer, cid)
    t = db.get(Tenant, actor.tenant_id)
    r = SettingsResolver(db, actor.tenant_id)
    modules = module_states(r)
    return {
        "customer": {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone},
        "tenant": tenant_contact(t),
        "consent": {
            "given": bool(c.consent_photos),
            "at": c.consent_at,
            "text": r.get("privacy.consent_text") or "",
        },
        "payments": r.get("payments.provider") if modules["payments"] else "off",
        "modules": {"customer_billing": modules["customer_billing"], "payments": modules["payments"]},
    }


def _photos(db, **where) -> list[dict[str, Any]]:
    q = select(Photo)
    for k, v in where.items():
        q = q.where(getattr(Photo, k) == v)
    return [
        {"id": p.id, "url": f"/api/files/{p.file_id}", "kind": p.kind, "plant_id": p.plant_id}
        for p in db.scalars(q.order_by(Photo.created_at))
    ]


def order_view(db, actor: Actor, o: PickupOrder, full: bool = False) -> dict[str, Any]:
    source = o.return_of_id or o.id
    billing = module_enabled(db, o.tenant_id, "customer_billing")
    quotes = (
        list(db.scalars(select(Quote).where(Quote.order_id == o.id).order_by(Quote.created_at.desc())))
        if billing
        else []
    )
    invoices = (
        list(
            db.scalars(
                select(Invoice)
                .where(Invoice.order_id == o.id, Invoice.kind == "customer")
                .order_by(Invoice.issue_date.desc())
            )
        )
        if billing
        else []
    )
    appt = appointment(db, o)
    a = db.get(Address, o.address_id)
    est = o.estimate or {}
    price = est.get("price") or {}
    out: dict[str, Any] = {
        "id": o.id,
        "number": o.number,
        "direction": o.direction,
        "status": o.status,
        "earliest_date": o.earliest_date,
        "latest_date": o.latest_date,
        "fixed_date": o.fixed_date,
        "appointment": appt,
        "progress": progress(o, bool(quotes), appt is not None),
        "address": {
            "street": a.street,
            "postal_code": a.postal_code,
            "city": a.city,
            "lat": a.lat,
            "lon": a.lon,
            "parking_notes": a.parking_notes,
            "bell_notes": a.bell_notes,
            "access_notes": a.access_notes,
        }
        if a
        else None,
        "price": {"gross": price.get("gross"), "net": price.get("net"), "vat_pct": price.get("vat_pct")}
        if price and billing
        else None,
        "quotes": [
            {
                "id": q.id,
                "number": q.number,
                "gross": q.gross_eur,
                "status": q.status,
                "created_at": q.created_at,
                "valid_until": q.valid_until,
                "pdf_url": f"/api/files/{q.file_id}" if q.file_id else None,
            }
            for q in quotes
        ],
        "invoices": [
            {
                "id": i.id,
                "number": i.number,
                "gross": i.gross_eur,
                "status": i.status,
                "issue_date": i.issue_date,
                "due_date": i.due_date,
                "pdf_url": f"/api/files/{i.file_id}" if i.file_id else None,
            }
            for i in invoices
        ],
        "return_wish": (o.return_wish or {}) if o.direction == "pickup" else None,
        "return_of_id": o.return_of_id,
    }
    if full:
        plants = []
        for p in db.scalars(
            select(Plant).where(Plant.order_id == source, Plant.deleted_at.is_(None)).order_by(Plant.number)
        ):
            sp = db.get(Species, p.species_id) if p.species_id else None
            g = geometry(p)
            photos = _photos(db, plant_id=p.id)
            plants.append(
                {
                    "id": p.id,
                    "number": p.number,
                    "name": sp.name if sp else (p.label or ""),
                    "height": round(g.total_h),
                    "pot_d": round(g.pot_d),
                    "photos": photos,
                    "missing": [k for k in GUIDED_PLANT if not any(ph["kind"] == k for ph in photos)],
                }
            )
        order_photos = _photos(db, order_id=source)
        out["plants"] = plants
        out["path_photos"] = [p for p in order_photos if p["kind"].startswith("path")]
        out["path_missing"] = [k for k in GUIDED_PATH if not any(p["kind"] == k for p in order_photos)]
        out["photo_check"] = est.get("photo_check")
        out["payments"] = [
            payment_dict(p)
            for p in db.scalars(
                select(Payment).where(Payment.order_id == o.id).order_by(Payment.created_at.desc())
            )
        ]
    return out


@router.get("/api/portal/orders")
def orders(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    _customer(actor, db)
    return [order_view(db, actor, o) for o in customer_orders(db, actor)]


@router.get("/api/portal/orders/{order_id}")
def order(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _customer(actor, db)
    return order_view(db, actor, own_order(db, actor, order_id), full=True)


class ConsentIn(BaseModel):
    accept: bool


@router.post("/api/portal/consent")
def consent(data: ConsentIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Consent to store photos of garden and home (text from the tenant's settings is saved with it)."""
    c = db.get(Customer, _customer(actor, db))
    if data.accept:
        c.consent_photos = True
        c.consent_at = datetime.now(UTC)
        c.consent_text = SettingsResolver(db, actor.tenant_id).get("privacy.consent_text") or ""
    else:
        c.consent_photos = False
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="customer",
        entity_id=c.id,
        action="consent",
        new={"given": data.accept},
    )
    return {"given": c.consent_photos}


@router.post("/api/portal/orders/{order_id}/photos", status_code=201)
async def upload(
    order_id: uuid.UUID,
    actor: CurrentActor,
    db: DB,
    file: UploadFile = File(...),
    kind: str = Form(...),
    plant_id: uuid.UUID | None = Form(None),
) -> dict[str, Any]:
    """Guided photo set: per plant front/side (with A4 sheet), top, pot; the path from start to end."""
    cid = _customer(actor, db)
    o = own_order(db, actor, order_id)
    c = db.get(Customer, cid)
    if not c.consent_photos:
        raise AppError("errors.consent_required", status_code=409)
    if kind not in GUIDED_PLANT + GUIDED_PATH:
        raise AppError("errors.validation")
    source = o.return_of_id or o.id
    if plant_id is not None:
        p = db.get(Plant, plant_id)
        if p is None or p.order_id != source:
            raise NotFound()
    if file.content_type not in IMAGE_TYPES:
        raise AppError("errors.file_type")
    raw = await file.read()
    if len(raw) > get_config().max_upload_mb * 1024 * 1024:
        raise AppError("errors.file_too_large", status_code=413)
    photo = save_photo(db, actor, raw, file.filename or "foto.jpg", kind, order_id=source, plant_id=plant_id)
    # the nursery's completeness check runs in the background (AI, or the test model)
    enqueue(
        db, "ai.check_order_photos", {"order_id": str(source)}, tenant_id=actor.tenant_id, created_by=None
    )
    return photo_dict(photo)


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    parking_notes: str | None = Field(default=None, max_length=1000)
    bell_notes: str | None = Field(default=None, max_length=200)
    access_notes: str | None = Field(default=None, max_length=1000)


@router.put("/api/portal/orders/{order_id}/location")
def location(order_id: uuid.UUID, data: LocationIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Pin where the plants are (and hints for parking, bell, access)."""
    _customer(actor, db)
    o = own_order(db, actor, order_id)
    a = db.get(Address, o.address_id)
    old = {"lat": a.lat, "lon": a.lon}
    a.lat, a.lon = data.lat, data.lon
    a.geocode_source = "customer"
    for k in ("parking_notes", "bell_notes", "access_notes"):
        v = getattr(data, k)
        if v is not None:
            setattr(a, k, v.strip() or None)
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="address",
        entity_id=a.id,
        action="update",
        old=old,
        new={"lat": a.lat, "lon": a.lon, "source": "customer"},
    )
    from app.api.planning import mark_needs_replan

    mark_needs_replan(db, actor.tenant_id, f"location:{o.number}", o.direction)
    return {"ok": True}


@router.post("/api/portal/quotes/{quote_id}/accept")
def accept_quote(quote_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _customer(actor, db)
    require_module(db, actor.tenant_id, "customer_billing")
    q = db.get(Quote, quote_id)
    if q is None:
        raise NotFound()
    o = own_order(db, actor, q.order_id)
    if q.status not in ("created", "sent"):
        raise AppError("errors.already_decided", status_code=409)
    if q.valid_until and q.valid_until < datetime.now(UTC):
        raise AppError("errors.quote_expired", status_code=409)
    q.status = "accepted"
    o.price_quoted = q.gross_eur
    confirmed = False
    if o.status == "draft" and bool(
        SettingsResolver(db, actor.tenant_id).get("portal.accept_quote_confirms")
    ):
        o.status = "confirmed"
        confirmed = True
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, actor.tenant_id, f"new_order:{o.number}", o.direction)
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="quote",
        entity_id=q.id,
        action="accept",
        new={"order": o.number, "gross": q.gross_eur, "order_confirmed": confirmed},
    )
    return {"status": q.status, "order_status": o.status}


class ReturnWishIn(BaseModel):
    earliest_date: date | None = None
    latest_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.put("/api/portal/orders/{order_id}/return-wish")
def return_wish(order_id: uuid.UUID, data: ReturnWishIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """When the plants should come back in spring. Applied to the return order while it is not planned."""
    _customer(actor, db)
    o = own_order(db, actor, order_id)
    if o.direction != "pickup":
        raise AppError("errors.validation")
    if data.earliest_date and data.latest_date and data.latest_date < data.earliest_date:
        raise AppError("errors.validation")
    o.return_wish = {
        "earliest_date": str(data.earliest_date) if data.earliest_date else None,
        "latest_date": str(data.latest_date) if data.latest_date else None,
        "notes": data.notes,
        "at": datetime.now(UTC).isoformat(),
    }
    ret = db.scalar(
        select(PickupOrder).where(PickupOrder.return_of_id == o.id, PickupOrder.deleted_at.is_(None))
    )
    applied = False
    if ret is not None and ret.status in ("draft", "confirmed"):
        if data.earliest_date:
            ret.earliest_date = data.earliest_date
        if data.latest_date:
            ret.latest_date = data.latest_date
        applied = True
        from app.api.planning import mark_needs_replan

        mark_needs_replan(db, actor.tenant_id, f"return_wish:{ret.number}", "return")
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="order",
        entity_id=o.id,
        action="return_wish",
        new=o.return_wish,
    )
    return {"return_wish": o.return_wish, "applied_to_return": applied}


# ---------------------------------------------------------------- payments


class PayIn(BaseModel):
    invoice_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None


@router.post("/api/portal/payments", status_code=201)
def pay(data: PayIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Start an online payment of an invoice (or an offer as prepayment); returns the checkout URL."""
    cid = _customer(actor, db)
    r = SettingsResolver(db, actor.tenant_id)
    require_module(db, actor.tenant_id, "payments", r)
    provider_name = r.get("payments.provider")
    if provider_name == "off":
        raise AppError("errors.module_off", status_code=409)
    amount, text, refs = open_amount(db, actor, data.invoice_id, data.quote_id)
    if already_paid(db, refs.get("invoice_id"), refs.get("quote_id")):
        raise AppError("errors.nothing_to_pay", status_code=409)
    p = Payment(
        tenant_id=actor.tenant_id,
        customer_id=cid,
        amount_eur=round(amount, 2),
        description=text,
        provider=provider_name,
        order_id=refs.get("order_id"),
        invoice_id=refs.get("invoice_id"),
        quote_id=refs.get("quote_id"),
    )
    db.add(p)
    db.flush()
    base = get_config().base_url
    checkout = provider_for(provider_name).create_checkout(
        str(p.id),
        p.amount_eur,
        text,
        f"{base}/kunde/auftraege/{p.order_id}?zahlung=ok",
        f"{base}/kunde/auftraege/{p.order_id}?zahlung=abgebrochen",
        r.get("payments.stripe_account") or None,
    )
    p.provider_ref = checkout.provider_ref
    p.checkout_url = checkout.url
    p.status = "pending"
    p.raw = checkout.raw
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="payment",
        entity_id=p.id,
        action="create",
        new={"amount": p.amount_eur},
    )
    return payment_dict(p)


@router.get("/api/portal/payments/{payment_id}")
def payment_status(payment_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    cid = _customer(actor, db)
    p = db.get(Payment, payment_id)
    if p is None or p.customer_id != cid:
        raise NotFound()
    return payment_dict(p)


class SimulateIn(BaseModel):
    success: bool = True


@router.post("/api/portal/payments/{payment_id}/simulate")
def simulate(payment_id: uuid.UUID, data: SimulateIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Test payment only: confirm or cancel the simulated checkout (no money moves)."""
    cid = _customer(actor, db)
    p = db.get(Payment, payment_id)
    if p is None or p.customer_id != cid:
        raise NotFound()
    if p.provider != "test":
        raise Forbidden()
    if data.success:
        mark_paid(db, p, ref=p.provider_ref)
    else:
        p.status = "cancelled"
    return payment_dict(p)


@public_router.post("/api/payments/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """Stripe events (signed). checkout.session.completed marks the payment as paid."""
    body = await request.body()
    if not verify_stripe_signature(
        body, request.headers.get("stripe-signature", ""), get_config().stripe_webhook_secret
    ):
        raise AppError("errors.unauthorized", status_code=400)
    import json

    event = json.loads(body)
    obj = (event.get("data") or {}).get("object") or {}
    if (
        event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded")
        and obj.get("payment_status", "paid") == "paid"
    ):
        pid = (obj.get("metadata") or {}).get("payment_id") or obj.get("client_reference_id")
        with system_session() as db:
            try:
                p = db.get(Payment, uuid.UUID(str(pid)))
            except ValueError:
                p = None
            if p is not None and p.provider == "stripe":
                mark_paid(db, p, ref=obj.get("id"), raw={"type": event.get("type"), "id": event.get("id")})
    return {"received": True}


# ---------------------------------------------------------------- staff side


@router.post("/api/customers/{customer_id}/portal-link")
def create_portal_link(customer_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Personal link for the customer portal (copy it into an e-mail or message)."""
    actor.require("customers.write")
    c = db.get(Customer, customer_id)
    if c is None or c.tenant_id != actor.tenant_id:
        raise NotFound()
    return portal_link(db, actor, c)


@router.get("/api/payments")
def list_payments(actor: CurrentActor, db: DB, order_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    actor.require("orders.read")
    q = select(Payment).where(Payment.tenant_id == actor.tenant_id)
    if order_id:
        q = q.where(Payment.order_id == order_id)
    return [payment_dict(p) for p in db.scalars(q.order_by(Payment.created_at.desc()).limit(500))]

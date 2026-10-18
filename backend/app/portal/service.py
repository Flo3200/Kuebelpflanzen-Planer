"""Customer portal: personal login link, what a customer may see, order status for customers,
payments (create checkout, mark paid)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.core.security import new_token, token_hash
from app.models.core import OneTimeCode, Tenant, User
from app.models.formulas import Quote
from app.models.orders import Customer, Photo, PickupOrder, StoredFile
from app.models.planning import Plan, Tour, TourStop
from app.models.platform import Invoice, Payment
from app.settings.service import SettingsResolver
from app.core.modules import require_module

# what the customer sees as progress of one order
PICKUP_STEPS = ["request", "offer", "confirmed", "planned", "picked_up", "stored", "returned"]
RETURN_STEPS = ["confirmed", "planned", "returned"]


def portal_link(db: Session, actor: Actor, customer: Customer) -> dict[str, Any]:
    """Creates the portal login of a customer (once) and a new personal link."""
    r = SettingsResolver(db, customer.tenant_id)
    require_module(db, customer.tenant_id, "portal", r)
    user = db.scalar(select(User).where(User.customer_id == customer.id, User.role == "customer"))
    if user is None:
        user = User(
            tenant_id=customer.tenant_id,
            name=customer.name,
            role="customer",
            customer_id=customer.id,
            extra_permissions=[],
            revoked_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.flush()
    code = new_token(24)
    days = int(r.get("portal.link_days"))
    db.add(
        OneTimeCode(
            tenant_id=customer.tenant_id,
            purpose="customer_link",
            code_hash=token_hash(code),
            user_id=user.id,
            created_by=actor.user_id,
            expires_at=datetime.now(UTC) + timedelta(days=days),
            reusable=True,
        )
    )
    audit.record(
        db,
        actor,
        tenant_id=customer.tenant_id,
        entity="customer",
        entity_id=customer.id,
        action="portal_link",
    )
    return {"url": f"{get_config().base_url}/kunde/login/{code}", "code": code, "valid_days": days}


def own_order(db: Session, actor: Actor, order_id: uuid.UUID) -> PickupOrder:
    order = db.get(PickupOrder, order_id)
    if (
        order is None
        or order.customer_id != actor.customer_id
        or order.tenant_id != actor.tenant_id
        or order.deleted_at
    ):
        raise NotFound()
    return order


def customer_orders(db: Session, actor: Actor) -> list[PickupOrder]:
    return list(
        db.scalars(
            select(PickupOrder)
            .where(
                PickupOrder.customer_id == actor.customer_id,
                PickupOrder.deleted_at.is_(None),
                PickupOrder.status != "cancelled",
            )
            .order_by(PickupOrder.created_at.desc())
        )
    )


def customer_owns_file(db: Session, actor: Actor, f: StoredFile) -> bool:
    """A customer may open photos of own orders, own offers and own invoices - nothing else."""
    orders = [o.id for o in customer_orders(db, actor)]
    sources = orders + [o.return_of_id for o in customer_orders(db, actor) if o.return_of_id]
    if not orders:
        return False
    if db.scalar(select(Photo.id).where(Photo.file_id == f.id, Photo.order_id.in_(sources))):
        return True
    if db.scalar(select(Quote.id).where(Quote.file_id == f.id, Quote.order_id.in_(orders))):
        return True
    return bool(
        db.scalar(
            select(Invoice.id).where(
                Invoice.file_id == f.id, Invoice.order_id.in_(orders), Invoice.kind == "customer"
            )
        )
    )


def appointment(db: Session, order: PickupOrder) -> dict[str, Any] | None:
    """Date and expected arrival window from the active plan of the order's direction."""
    row = db.execute(
        select(TourStop, Tour)
        .join(Tour, Tour.id == TourStop.tour_id)
        .join(Plan, Plan.id == Tour.plan_id)
        .where(TourStop.order_id == order.id, Plan.is_active.is_(True))
    ).first()
    if row is None:
        return None
    stop, tour = row
    lo, hi = max(0, stop.arrival_min - 30), stop.arrival_min + 30
    return {
        "date": tour.date,
        "from": f"{lo // 60:02d}:{lo % 60:02d}",
        "to": f"{hi // 60:02d}:{hi % 60:02d}",
        "team_size": stop.team_size,
        "status": stop.status,
    }


def progress(order: PickupOrder, has_quote: bool, planned: bool) -> dict[str, Any]:
    if order.direction == "return":
        steps = RETURN_STEPS
        current = "returned" if order.status == "returned" else "planned" if planned else "confirmed"
    else:
        steps = PICKUP_STEPS
        current = {
            "draft": "offer" if has_quote else "request",
            "confirmed": "planned" if planned else "confirmed",
            "planned": "planned",
            "picked_up": "picked_up",
            "stored": "stored",
            "returned": "returned",
        }.get(order.status, "request")
    return {"steps": steps, "current": current, "index": steps.index(current)}


# ---------------------------------------------------------------- payments


def open_amount(
    db: Session, actor: Actor, invoice_id: uuid.UUID | None, quote_id: uuid.UUID | None
) -> tuple[float, str, dict[str, Any]]:
    if invoice_id:
        inv = db.get(Invoice, invoice_id)
        if inv is None or inv.kind != "customer" or inv.order_id is None:
            raise NotFound()
        own_order(db, actor, inv.order_id)
        if inv.status != "issued" or inv.gross_eur <= 0:
            raise AppError("errors.nothing_to_pay", status_code=409)
        return inv.gross_eur, f"Rechnung {inv.number}", {"invoice_id": inv.id, "order_id": inv.order_id}
    if quote_id:
        q = db.get(Quote, quote_id)
        if q is None:
            raise NotFound()
        own_order(db, actor, q.order_id)
        if q.status not in ("created", "sent", "accepted") or q.gross_eur <= 0:
            raise AppError("errors.nothing_to_pay", status_code=409)
        return q.gross_eur, f"Angebot {q.number}", {"quote_id": q.id, "order_id": q.order_id}
    raise AppError("errors.validation")


def already_paid(db: Session, invoice_id: uuid.UUID | None, quote_id: uuid.UUID | None) -> bool:
    cond = []
    if invoice_id:
        cond.append(Payment.invoice_id == invoice_id)
    if quote_id:
        cond.append(Payment.quote_id == quote_id)
    return (
        bool(cond) and db.scalar(select(Payment.id).where(or_(*cond), Payment.status == "paid")) is not None
    )


def mark_paid(
    db: Session, payment: Payment, ref: str | None = None, raw: dict[str, Any] | None = None
) -> Payment:
    if payment.status == "paid":
        return payment
    now = datetime.now(UTC)
    payment.status = "paid"
    payment.paid_at = now
    if ref:
        payment.provider_ref = ref
    if raw:
        payment.raw = {**(payment.raw or {}), "event": raw}
    if payment.invoice_id:
        inv = db.get(Invoice, payment.invoice_id)
        if inv is not None and inv.status == "issued":
            inv.status = "paid"
            inv.paid_at = now
            inv.payment_provider = payment.provider
            inv.payment_ref = payment.provider_ref
    if payment.quote_id:
        q = db.get(Quote, payment.quote_id)
        if q is not None:
            q.status = "paid"
    from app.core.context import system_actor

    audit.record(
        db,
        system_actor(payment.tenant_id, label=f"Zahlung {payment.provider}"),
        tenant_id=payment.tenant_id,
        entity="payment",
        entity_id=payment.id,
        action="paid",
        new={"amount": payment.amount_eur},
    )
    db.flush()
    return payment


def payment_dict(p: Payment) -> dict[str, Any]:
    return {
        "id": p.id,
        "order_id": p.order_id,
        "invoice_id": p.invoice_id,
        "quote_id": p.quote_id,
        "amount": p.amount_eur,
        "currency": p.currency,
        "description": p.description,
        "provider": p.provider,
        "status": p.status,
        "checkout_url": p.checkout_url,
        "created_at": p.created_at,
        "paid_at": p.paid_at,
    }


def tenant_contact(t: Tenant) -> dict[str, Any]:
    return {
        "name": t.name,
        "phone": t.phone,
        "email": t.email,
        "street": t.street,
        "postal_code": t.postal_code,
        "city": t.city,
    }

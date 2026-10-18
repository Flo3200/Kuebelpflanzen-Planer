"""Platform billing per tenant (modules: subscription, per picked-up plant, AI usage) and optional
invoices of a tenant to its own customers. Amounts are frozen in the invoice; PDFs are stored files."""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, Conflict, NotFound
from app.core.numbering import next_number
from app.models.ai import AIUsage
from app.models.core import Tenant
from app.models.field import TourEvent
from app.models.orders import Address, Customer, PickupOrder, Plant, StoredFile
from app.models.planning import TourStop
from app.models.platform import Invoice, PlatformCounter
from app.pdf.invoice import render_invoice
from app.settings.service import SettingsResolver
from app.storage.backend import get_storage, new_key, sha256


def platform_number(db: Session, year: int, prefix: str = "KP") -> str:
    """Consecutive invoice number of the platform operator, per year: KP-2026-00001."""
    name = f"invoice-{year}"
    row = db.scalar(select(PlatformCounter).where(PlatformCounter.name == name).with_for_update())
    if row is None:
        row = PlatformCounter(name=name, value=0)
        db.add(row)
        db.flush()
        row = db.scalar(select(PlatformCounter).where(PlatformCounter.name == name).with_for_update())
    row.value += 1
    db.flush()
    return f"{prefix}-{year}-{row.value:05d}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def previous_month(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    first = today.replace(day=1)
    last_prev = first - timedelta(days=1)
    return month_bounds(last_prev.year, last_prev.month)


def _dt(d: date, end: bool = False) -> datetime:
    return datetime.combine(d + timedelta(days=1) if end else d, time.min, tzinfo=UTC)


def picked_up_plants(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> int:
    """Plants of pickup orders loaded in the period (first 'loaded'/'leave' event of the stop)."""
    first = (
        select(TourStop.order_id, func.min(TourEvent.at).label("at"))
        .join(TourEvent, TourEvent.stop_id == TourStop.id)
        .where(
            TourEvent.tenant_id == tenant_id,
            TourEvent.kind.in_(("loaded", "leave")),
            TourEvent.voided.is_(False),
        )
        .group_by(TourStop.order_id)
        .subquery()
    )
    orders = list(
        db.scalars(
            select(PickupOrder)
            .join(first, first.c.order_id == PickupOrder.id)
            .where(first.c.at >= _dt(start), first.c.at < _dt(end, True), PickupOrder.direction == "pickup")
        )
    )
    if not orders:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(Plant)
            .where(Plant.order_id.in_([o.id for o in orders]), Plant.deleted_at.is_(None))
        )
        or 0
    )


def platform_lines(db: Session, tenant: Tenant, start: date, end: date) -> list[dict[str, Any]]:
    r = SettingsResolver(db, tenant.id)
    lines: list[dict[str, Any]] = []
    sub = float(r.get("billing.subscription_eur"))
    if sub > 0:
        if r.get("billing.subscription_period") == "yearly":
            anniversary = tenant.created_at.month if tenant.created_at else 1
            if start.month == anniversary:
                lines.append(
                    {
                        "module": "subscription",
                        "text": f"Jahresgebühr Plattform {start.year}/{start.year + 1}",
                        "quantity": 1,
                        "unit": "Jahr",
                        "unit_price": sub,
                        "amount": round(sub, 2),
                    }
                )
        else:
            lines.append(
                {
                    "module": "subscription",
                    "text": f"Monatsgebühr Plattform {start:%m/%Y}",
                    "quantity": 1,
                    "unit": "Monat",
                    "unit_price": sub,
                    "amount": round(sub, 2),
                }
            )
    per_plant = float(r.get("billing.per_plant_eur"))
    if per_plant > 0:
        n = picked_up_plants(db, tenant.id, start, end)
        if n:
            lines.append(
                {
                    "module": "per_plant",
                    "text": "Abgeholte Pflanzen",
                    "quantity": n,
                    "unit": "Stk.",
                    "unit_price": per_plant,
                    "amount": round(n * per_plant, 2),
                }
            )
    if bool(r.get("billing.ai_enabled")):
        markup = float(r.get("billing.ai_markup_pct"))
        rows = db.execute(
            select(
                AIUsage.model,
                func.sum(AIUsage.input_tokens),
                func.sum(AIUsage.output_tokens),
                func.sum(AIUsage.cost_eur),
                func.count(),
            )
            .where(
                AIUsage.tenant_id == tenant.id,
                AIUsage.key_mode == "platform",
                AIUsage.created_at >= _dt(start),
                AIUsage.created_at < _dt(end, True),
            )
            .group_by(AIUsage.model)
            .order_by(AIUsage.model)
        ).all()
        for model, tin, tout, cost, calls in rows:
            amount = round(float(cost or 0) * (1 + markup / 100), 2)
            if amount <= 0:
                continue
            text = f"KI-Nutzung {model}: {int(tin or 0):,} Eingabe- und {int(tout or 0):,} Ausgabe-Tokens ({calls} Aufrufe)".replace(
                ",", "."
            )
            if markup:
                text += f", inkl. {markup:g} % Aufschlag"
            lines.append(
                {
                    "module": "ai",
                    "text": text,
                    "quantity": None,
                    "unit": None,
                    "unit_price": None,
                    "amount": amount,
                }
            )
    return lines


def issuer_of_platform(db: Session) -> dict[str, Any]:
    return dict(SettingsResolver(db, None).get("billing.issuer") or {})


def party_of_tenant(t: Tenant) -> dict[str, Any]:
    return {
        "name": t.legal_name or t.name,
        "street": t.street,
        "postal_code": t.postal_code,
        "city": t.city,
        "vat_id": t.vat_id,
        "tax_number": t.tax_number,
        "iban": t.iban,
        "email": t.email,
        "phone": t.phone,
    }


def _store_pdf(
    db: Session, tenant_id: uuid.UUID, data: bytes, filename: str, created_by: uuid.UUID | None
) -> StoredFile:
    key = new_key(tenant_id, "invoice", ".pdf")
    get_storage().put(key, data, "application/pdf")
    row = StoredFile(
        tenant_id=tenant_id,
        key=key,
        filename=filename,
        content_type="application/pdf",
        size=len(data),
        sha256=sha256(data),
        purpose="invoice",
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def _totals(lines: list[dict[str, Any]], vat_pct: float, small: bool) -> tuple[float, float, float]:
    net = round(sum(x["amount"] for x in lines), 2)
    vat = 0.0 if small else round(net * vat_pct / 100, 2)
    return net, vat, round(net + vat, 2)


def preview_platform_invoice(db: Session, tenant: Tenant, start: date, end: date) -> dict[str, Any]:
    pr = SettingsResolver(db, None)
    small = bool(pr.get("billing.small_business"))
    vat_pct = 0.0 if small else float(pr.get("billing.vat_pct"))
    lines = platform_lines(db, tenant, start, end)
    net, vat, gross = _totals(lines, vat_pct, small)
    return {
        "tenant_id": tenant.id,
        "period_start": start,
        "period_end": end,
        "lines": lines,
        "net": net,
        "vat_pct": vat_pct,
        "vat": vat,
        "gross": gross,
        "small_business": small,
    }


def create_platform_invoice(
    db: Session,
    actor: Actor,
    tenant: Tenant,
    start: date,
    end: date,
    *,
    allow_empty: bool = False,
    issue: date | None = None,
) -> Invoice | None:
    existing = db.scalar(
        select(Invoice).where(
            Invoice.kind == "platform",
            Invoice.tenant_id == tenant.id,
            Invoice.period_start == start,
            Invoice.period_end == end,
            Invoice.status != "cancelled",
            Invoice.cancels_id.is_(None),
        )
    )
    if existing is not None:
        raise Conflict("errors.invoice_exists", number=existing.number)
    p = preview_platform_invoice(db, tenant, start, end)
    if not p["lines"] and not allow_empty:
        return None
    pr = SettingsResolver(db, None)
    issue = issue or date.today()
    number = platform_number(db, issue.year)
    issuer = issuer_of_platform(db)
    recipient = party_of_tenant(tenant)
    due = issue + timedelta(days=int(pr.get("billing.payment_days")))
    inv = Invoice(
        tenant_id=tenant.id,
        kind="platform",
        number=number,
        period_start=start,
        period_end=end,
        issue_date=issue,
        due_date=due,
        issuer=issuer,
        recipient=recipient,
        lines=p["lines"],
        net_eur=p["net"],
        vat_pct=p["vat_pct"],
        vat_eur=p["vat"],
        gross_eur=p["gross"],
        small_business=p["small_business"],
        created_by=actor.user_id,
    )
    pdf = render_invoice(
        {
            "number": number,
            "title": "Rechnung",
            "issue_date": issue,
            "due_date": due,
            "period_start": start,
            "period_end": end,
            "issuer": issuer,
            "recipient": recipient,
            "lines": p["lines"],
            "net": p["net"],
            "vat_pct": p["vat_pct"],
            "vat": p["vat"],
            "gross": p["gross"],
            "small_business": p["small_business"],
            "intro": "für die Nutzung der Planungsplattform berechnen wir Ihnen:",
        }
    )
    inv.file_id = _store_pdf(db, tenant.id, pdf, f"rechnung-{number}.pdf", actor.user_id).id
    db.add(inv)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tenant.id,
        entity="invoice",
        entity_id=inv.id,
        action="create",
        new={"number": number, "gross": inv.gross_eur},
    )
    return inv


def cancel_invoice(db: Session, actor: Actor, inv: Invoice) -> Invoice:
    """Cancellation invoice (Stornorechnung) with negative amounts; the original stays unchanged."""
    if inv.status == "cancelled" or inv.cancels_id is not None:
        raise AppError("errors.already_decided", status_code=409)
    issue = date.today()
    if inv.kind == "platform":
        number = platform_number(db, issue.year)
    else:
        number = f"S-{issue.year}-{next_number(db, inv.tenant_id, f'customer_invoice_{issue.year}'):04d}"
    lines = [
        {
            **x,
            "amount": -x["amount"],
            "unit_price": -x["unit_price"] if x.get("unit_price") is not None else None,
        }
        for x in inv.lines
    ]
    storno = Invoice(
        tenant_id=inv.tenant_id,
        kind=inv.kind,
        number=number,
        order_id=inv.order_id,
        period_start=inv.period_start,
        period_end=inv.period_end,
        issue_date=issue,
        due_date=None,
        issuer=inv.issuer,
        recipient=inv.recipient,
        lines=lines,
        net_eur=-inv.net_eur,
        vat_pct=inv.vat_pct,
        vat_eur=-inv.vat_eur,
        gross_eur=-inv.gross_eur,
        small_business=inv.small_business,
        cancels_id=inv.id,
        created_by=actor.user_id,
    )
    pdf = render_invoice(
        {
            "number": number,
            "title": "Stornorechnung",
            "issue_date": issue,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "issuer": inv.issuer,
            "recipient": inv.recipient,
            "lines": lines,
            "net": storno.net_eur,
            "vat_pct": inv.vat_pct,
            "vat": storno.vat_eur,
            "gross": storno.gross_eur,
            "small_business": inv.small_business,
            "cancels": inv.number,
        }
    )
    storno.file_id = _store_pdf(db, inv.tenant_id, pdf, f"storno-{number}.pdf", actor.user_id).id
    db.add(storno)
    inv.status = "cancelled"
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=inv.tenant_id,
        entity="invoice",
        entity_id=inv.id,
        action="cancel",
        new={"storno": number},
    )
    return storno


# ---------------------------------------------------------------- tenant -> own customer


def create_customer_invoice(db: Session, actor: Actor, order: PickupOrder) -> Invoice:
    tenant = db.get(Tenant, order.tenant_id)
    customer = db.get(Customer, order.customer_id)
    address = db.get(Address, order.address_id)
    if tenant is None or customer is None or address is None:
        raise NotFound()
    est = order.estimate or {}
    price = est.get("price") or {}
    if not price:
        raise AppError("errors.no_estimate")
    r = SettingsResolver(db, tenant.id)
    small = bool(r.get("costs.small_business"))
    vat_pct = 0.0 if small else float(price.get("vat_pct") or r.get("costs.vat_pct"))
    from app.pdf.quote import quote_lines

    gross_price = float(order.price_final or order.price_quoted or price.get("gross") or 0)
    net_price = round(gross_price / (1 + vat_pct / 100), 2) if vat_pct else gross_price
    base = quote_lines(est, include_vat=False)
    scale = (net_price / sum(x["amount"] for x in base)) if base and sum(x["amount"] for x in base) else 1.0
    lines = [
        {
            "text": x["text"],
            "quantity": None,
            "unit": None,
            "unit_price": None,
            "amount": round(x["amount"] * scale, 2),
        }
        for x in base
    ]
    diff = round(net_price - sum(x["amount"] for x in lines), 2)
    if lines and abs(diff) >= 0.01:
        lines[-1]["amount"] = round(lines[-1]["amount"] + diff, 2)
    net, vat, gross = _totals(lines, vat_pct, small)
    issue = date.today()
    number = f"R-{issue.year}-{next_number(db, tenant.id, f'customer_invoice_{issue.year}'):04d}"
    issuer = party_of_tenant(tenant)
    recipient = {
        "name": customer.name,
        "extra": customer.company,
        "street": address.street,
        "postal_code": address.postal_code,
        "city": address.city,
        "customer_no": getattr(customer, "number", None),
    }
    due = issue + timedelta(days=int(SettingsResolver(db, None).get("billing.payment_days")))
    inv = Invoice(
        tenant_id=tenant.id,
        kind="customer",
        number=number,
        order_id=order.id,
        issue_date=issue,
        due_date=due,
        issuer=issuer,
        recipient=recipient,
        lines=lines,
        net_eur=net,
        vat_pct=vat_pct,
        vat_eur=vat,
        gross_eur=gross,
        small_business=small,
        created_by=actor.user_id,
    )
    pdf = render_invoice(
        {
            "number": number,
            "title": "Rechnung",
            "issue_date": issue,
            "due_date": due,
            "issuer": issuer,
            "recipient": recipient,
            "lines": lines,
            "net": net,
            "vat_pct": vat_pct,
            "vat": vat,
            "gross": gross,
            "small_business": small,
            "reference": f"Auftrag {order.number}",
            "service_date": _service_date(db, order),
            "intro": "für die Abholung Ihrer Kübelpflanzen zur Überwinterung berechnen wir Ihnen:",
        }
    )
    inv.file_id = _store_pdf(db, tenant.id, pdf, f"rechnung-{number}.pdf", actor.user_id).id
    db.add(inv)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tenant.id,
        entity="invoice",
        entity_id=inv.id,
        action="create",
        new={"number": number, "order": order.number, "gross": gross},
    )
    return inv


def _service_date(db: Session, order: PickupOrder) -> date:
    at = db.scalar(
        select(func.min(TourEvent.at))
        .join(TourStop, TourStop.id == TourEvent.stop_id)
        .where(TourStop.order_id == order.id, TourEvent.kind.in_(("loaded", "leave")))
    )
    return at.date() if at else (order.fixed_date or date.today())


def invoice_dict(i: Invoice) -> dict[str, Any]:
    return {
        "id": i.id,
        "kind": i.kind,
        "number": i.number,
        "tenant_id": i.tenant_id,
        "order_id": i.order_id,
        "period_start": i.period_start,
        "period_end": i.period_end,
        "issue_date": i.issue_date,
        "due_date": i.due_date,
        "recipient": i.recipient,
        "lines": i.lines,
        "net": i.net_eur,
        "vat_pct": i.vat_pct,
        "vat": i.vat_eur,
        "gross": i.gross_eur,
        "small_business": i.small_business,
        "status": i.status,
        "paid_at": i.paid_at,
        "cancels_id": i.cancels_id,
        "pdf_url": f"/api/billing/invoices/{i.id}/pdf",
    }


def usage_overview(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> dict[str, Any]:
    """AI usage per function and model, plants picked up, open preview of the current month."""
    rows = db.execute(
        select(
            AIUsage.function,
            AIUsage.model,
            AIUsage.key_mode,
            func.count(),
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
            func.sum(AIUsage.cost_eur),
        )
        .where(
            AIUsage.tenant_id == tenant_id,
            AIUsage.created_at >= _dt(start),
            AIUsage.created_at < _dt(end, True),
        )
        .group_by(AIUsage.function, AIUsage.model, AIUsage.key_mode)
    ).all()
    ai = [
        {
            "function": f,
            "model": m,
            "key_mode": k,
            "calls": n,
            "input_tokens": int(i or 0),
            "output_tokens": int(o or 0),
            "cost_eur": round(float(c or 0), 4),
        }
        for f, m, k, n, i, o, c in rows
    ]
    by_month: dict[str, float] = defaultdict(float)
    month = func.date_trunc(literal_column("'month'"), AIUsage.created_at)
    for d, c in db.execute(
        select(month, func.sum(AIUsage.cost_eur)).where(AIUsage.tenant_id == tenant_id).group_by(month)
    ).all():
        by_month[d.strftime("%Y-%m")] += float(c or 0)
    return {
        "period_start": start,
        "period_end": end,
        "ai": ai,
        "ai_by_month": dict(sorted(by_month.items())),
        "plants_picked_up": picked_up_plants(db, tenant_id, start, end),
    }

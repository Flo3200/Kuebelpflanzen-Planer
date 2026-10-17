"""Estimates per order, quotes (PDF), pricing overview, weight calibration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.api.files import store_file
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.numbering import next_number
from app.jobs.queue import enqueue, run_now
from app.models.core import Tenant
from app.models.formulas import Quote
from app.models.masterdata import Species
from app.models.orders import Address, Customer, PickupOrder, Plant
from app.pdf.quote import quote_lines, render_quote
from app.settings.service import SettingsResolver, set_value
from app.timemodel.estimate import Estimator
from app.timemodel.service import refresh_order_estimate

router = APIRouter(tags=["estimates"])


def _order(db, actor, order_id: uuid.UUID) -> PickupOrder:
    order = db.get(PickupOrder, order_id)
    if order is None or order.deleted_at is not None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    return order


@router.get("/api/orders/{order_id}/estimate")
def order_estimate(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Recompute and return duration, labour time, team size, costs and price of an order."""
    actor.require("orders.read")
    order = _order(db, actor, order_id)
    return refresh_order_estimate(db, order)


@router.post("/api/estimates/refresh")
def refresh(actor: CurrentActor, db: DB, sync: bool = False) -> dict[str, Any]:
    actor.require("orders.write")
    job = enqueue(db, "estimates.refresh", {}, tenant_id=actor.require_tenant(), created_by=actor.user_id)
    if sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result}


@router.get("/api/pricing/overview")
def pricing_overview(actor: CurrentActor, db: DB, season: int | None = None) -> dict[str, Any]:
    """Price, self cost and cost coverage per order (before planning: estimated drive share)."""
    actor.require("orders.read")
    tid = actor.require_tenant()
    stmt = (
        select(PickupOrder, Customer.name)
        .join(Customer, Customer.id == PickupOrder.customer_id)
        .where(
            PickupOrder.tenant_id == tid, PickupOrder.deleted_at.is_(None), PickupOrder.status != "cancelled"
        )
    )
    if season:
        stmt = stmt.where(PickupOrder.season == season)
    rows = []
    totals = {"gross": 0.0, "net": 0.0, "self_cost": 0.0, "labour_min": 0.0}
    for order, name in db.execute(stmt.order_by(PickupOrder.number)).all():
        est = order.estimate or {}
        price = est.get("price") or {}
        costs = est.get("costs") or {}
        plan = est.get("plan_costs")
        rows.append(
            {
                "id": order.id,
                "number": order.number,
                "customer": name,
                "status": order.status,
                "labour_min": est.get("labour_min"),
                "team_size": est.get("team_size"),
                "gross": price.get("gross"),
                "net": price.get("net"),
                "self_cost": costs.get("self_cost"),
                "coverage_pct": price.get("coverage_pct"),
                "plan_self_cost": plan.get("self_cost") if plan else None,
                "plan_coverage_pct": plan.get("coverage_pct") if plan else None,
            }
        )
        for k in ("gross", "net", "self_cost", "labour_min"):
            totals[k] += float(
                (price if k in ("gross", "net") else costs if k == "self_cost" else est).get(k) or 0
            )
    totals["coverage_pct"] = (
        round(totals["net"] / totals["self_cost"] * 100, 1) if totals["self_cost"] else None
    )
    return {
        "rows": rows,
        "totals": {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()},
    }


@router.post("/api/orders/{order_id}/quote", status_code=201)
def create_quote(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Create a quote with the current estimate and store it as PDF."""
    actor.require("pricing.write")
    order = _order(db, actor, order_id)
    estimate = refresh_order_estimate(db, order)
    price = estimate.get("price") or {}
    if "gross" not in price:
        raise AppError(
            "errors.formula_eval", detail=estimate.get("error") or price.get("error") or "Preis fehlt"
        )
    tenant = db.get(Tenant, order.tenant_id)
    customer = db.get(Customer, order.customer_id)
    address = db.get(Address, order.address_id)
    resolver = SettingsResolver(db, order.tenant_id)
    include_vat = bool(resolver.get("pricing.prices_include_vat"))
    lines = quote_lines(estimate, include_vat)
    year = datetime.now(UTC).year
    number_text = f"AN-{year}-{next_number(db, order.tenant_id, f'quote-{year}'):04d}"
    source = order.return_of_id or order.id
    plants = []
    for p, sname in db.execute(
        select(Plant, Species.name)
        .outerjoin(Species, Species.id == Plant.species_id)
        .where(Plant.order_id == source, Plant.deleted_at.is_(None))
        .order_by(Plant.number)
    ).all():
        plants.append(
            {
                "number": p.number,
                "display": " ".join(x for x in (sname, p.label) if x) or "Pflanze",
                "total_height_cm": p.total_height_cm,
                "pot_diameter_cm": p.pot_diameter_cm,
                "weight_kg": p.weight_kg,
            }
        )
    pdf = render_quote(
        tenant,
        customer,
        address,
        order,
        estimate,
        plants,
        number_text,
        price["net"],
        price["vat_pct"],
        price["gross"],
        lines,
        prices_include_vat=include_vat,
    )
    stored = store_file(db, actor, pdf, f"Angebot-{number_text}.pdf", "application/pdf", "quote")
    quote = Quote(
        tenant_id=order.tenant_id,
        order_id=order.id,
        number=number_text,
        net_eur=price["net"],
        vat_pct=price["vat_pct"],
        gross_eur=price["gross"],
        lines=lines,
        file_id=stored.id,
        valid_until=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(quote)
    order.price_quoted = price["gross"]
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=order.tenant_id,
        entity="quote",
        entity_id=quote.id,
        action="create",
        new={"number": number_text, "gross": price["gross"]},
    )
    return quote_dict(quote)


def quote_dict(q: Quote) -> dict[str, Any]:
    return {
        "id": q.id,
        "number": q.number,
        "net_eur": q.net_eur,
        "vat_pct": q.vat_pct,
        "gross_eur": q.gross_eur,
        "lines": q.lines,
        "valid_until": q.valid_until,
        "created_at": q.created_at,
        "status": q.status,
        "url": f"/api/files/{q.file_id}?download=true" if q.file_id else None,
        "order_id": q.order_id,
    }


@router.get("/api/orders/{order_id}/quotes")
def list_quotes(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("orders.read")
    _order(db, actor, order_id)
    return [
        quote_dict(q)
        for q in db.scalars(select(Quote).where(Quote.order_id == order_id).order_by(Quote.created_at.desc()))
    ]


@router.get("/api/weights/calibration")
def weight_calibration(actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Proposed calibration factor from plants with a real weighing (least squares through origin)."""
    actor.require("orders.read")
    tid = actor.require_tenant()
    resolver = SettingsResolver(db, tid)
    current = float(resolver.get("weight.calibration_factor"))
    rows = list(
        db.scalars(
            select(Plant).where(
                Plant.tenant_id == tid, Plant.weight_measured_kg.isnot(None), Plant.deleted_at.is_(None)
            )
        )
    )
    from app.timemodel.plantfill import estimate_weight

    pairs = []
    est = Estimator(db, tid)
    for p in rows:
        e, _ = estimate_weight(p, resolver, est.species_of(p), set(p.estimated_fields or []))
        if e > 0:
            pairs.append((e, float(p.weight_measured_kg)))
    if len(pairs) < 3:
        return {"n": len(pairs), "current": current, "proposed": None}
    k = sum(e * m for e, m in pairs) / sum(e * e for e, _ in pairs)
    proposed = current * k
    mae_before = sum(abs(e - m) for e, m in pairs) / len(pairs)
    mae_after = sum(abs(e * k - m) for e, m in pairs) / len(pairs)
    return {
        "n": len(pairs),
        "current": round(current, 3),
        "proposed": round(proposed, 3),
        "mae_before_kg": round(mae_before, 1),
        "mae_after_kg": round(mae_after, 1),
    }


@router.post("/api/weights/calibration/apply")
def apply_weight_calibration(actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.settings")
    proposal = weight_calibration(actor, db)
    if proposal.get("proposed") is None:
        raise AppError("errors.validation")
    entry = set_value(
        db,
        actor,
        scope="tenant",
        key="weight.calibration_factor",
        value=proposal["proposed"],
        tenant_id=actor.require_tenant(),
    )
    # recompute estimated weights
    resolver = SettingsResolver(db, actor.tenant_id)
    from app.timemodel.plantfill import complete_plant

    est = Estimator(db, actor.tenant_id)
    for p in db.scalars(select(Plant).where(Plant.tenant_id == actor.tenant_id, Plant.deleted_at.is_(None))):
        if "weight_kg" in (p.estimated_fields or []):
            p.weight_kg = None
            complete_plant(db, p, resolver, est.species_of(p))
    from app.timemodel.service import schedule_refresh

    schedule_refresh(db, actor.tenant_id)
    return {**proposal, "applied": True, "audit_id": entry.id}

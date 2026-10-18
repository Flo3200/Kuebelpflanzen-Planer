"""Privacy: export and erasure of a customer's data, automatic deletion after the retention periods.

- Photos are deleted after `privacy.photo_retention_days` once their order is finished (returned,
  cancelled) or untouched for that long; photos of drafts that never became an order as well.
- Customers without activity for `privacy.customer_retention_days` are erased.
- Erasure keeps what is not personal (plants, measurements, tours: they train the model) and
  removes names, contact data, street, coordinates, notes, messages, photos and offers.
  Invoices stay because of the retention obligation (`privacy.invoice_retention_years`); they are
  deleted when that period has ended.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.models.core import AuditLog
from app.models.field import Deviation
from app.models.formulas import Quote
from app.models.orders import (
    AccessPath,
    Address,
    Customer,
    Draft,
    PathSegment,
    Photo,
    PickupOrder,
    Plant,
    StoredFile,
)
from app.models.platform import Invoice
from app.settings.service import SettingsResolver
from app.storage.backend import get_storage

ERASED = "gelöscht"
FINISHED = ("returned", "cancelled")


def _jsonable(row: Any, skip: tuple[str, ...] = ()) -> dict[str, Any]:
    out = {}
    for col in row.__table__.columns:
        if col.name in skip:
            continue
        v = getattr(row, col.name)
        if isinstance(v, (uuid.UUID, datetime, date)):
            v = str(v)
        out[col.name] = v
    return out


def _delete_file(db: Session, file_id: uuid.UUID | None) -> None:
    if file_id is None:
        return
    f = db.get(StoredFile, file_id)
    if f is None:
        return
    try:
        get_storage().delete(f.key)
    except FileNotFoundError:
        pass
    db.delete(f)


def delete_photo(db: Session, p: Photo) -> None:
    fid = p.file_id
    db.delete(p)
    db.flush()
    _delete_file(db, fid)


def customer_orders(db: Session, customer_id: uuid.UUID) -> list[PickupOrder]:
    return list(db.scalars(select(PickupOrder).where(PickupOrder.customer_id == customer_id)))


def export_customer(db: Session, actor: Actor, customer: Customer) -> bytes:
    """ZIP with all data of one customer: data.json, photos, offers and invoices as PDF."""
    orders = customer_orders(db, customer.id)
    order_ids = [o.id for o in orders]
    data: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "customer": _jsonable(customer),
        "addresses": [
            _jsonable(a) for a in db.scalars(select(Address).where(Address.customer_id == customer.id))
        ],
        "orders": [],
        "drafts": [
            _jsonable(d, ("extracted", "confidence"))
            for d in db.scalars(select(Draft).where(Draft.customer_id == customer.id))
        ],
        "deviations": [
            _jsonable(d) for d in db.scalars(select(Deviation).where(Deviation.order_id.in_(order_ids)))
        ]
        if order_ids
        else [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        storage = get_storage()
        for o in orders:
            od = _jsonable(o, ("estimate",))
            od["plants"] = [_jsonable(p) for p in db.scalars(select(Plant).where(Plant.order_id == o.id))]
            paths = []
            for ap in db.scalars(select(AccessPath).where(AccessPath.order_id == o.id)):
                pd = _jsonable(ap)
                pd["segments"] = [
                    _jsonable(s) for s in db.scalars(select(PathSegment).where(PathSegment.path_id == ap.id))
                ]
                paths.append(pd)
            od["paths"] = paths
            od["quotes"] = [_jsonable(q) for q in db.scalars(select(Quote).where(Quote.order_id == o.id))]
            od["invoices"] = [
                _jsonable(i, ("issuer",)) for i in db.scalars(select(Invoice).where(Invoice.order_id == o.id))
            ]
            data["orders"].append(od)
            for p in db.scalars(select(Photo).where(Photo.order_id == o.id)):
                f = db.get(StoredFile, p.file_id)
                if f is not None:
                    try:
                        z.writestr(
                            f"fotos/{o.number}/{p.kind}-{p.id}{_ext(f.content_type)}", storage.get(f.key)
                        )
                    except FileNotFoundError:
                        pass
            for doc in [
                *db.scalars(select(Quote).where(Quote.order_id == o.id)),
                *db.scalars(select(Invoice).where(Invoice.order_id == o.id)),
            ]:
                f = db.get(StoredFile, doc.file_id) if doc.file_id else None
                if f is not None:
                    try:
                        z.writestr(f"dokumente/{f.filename}", storage.get(f.key))
                    except FileNotFoundError:
                        pass
        z.writestr("daten.json", json.dumps(data, ensure_ascii=False, indent=2, default=str))
        z.writestr(
            "LIESMICH.txt",
            "Alle gespeicherten Daten zu diesem Kunden: daten.json (Stammdaten, Adressen, Aufträge, "
            "Pflanzen, Wege, Angebote, Rechnungen, Meldungen), Fotos und Dokumente als Dateien.\n",
        )
    audit.record(
        db, actor, tenant_id=customer.tenant_id, entity="customer", entity_id=customer.id, action="export"
    )
    return buf.getvalue()


def _ext(content_type: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}.get(content_type, "")


def erase_customer(db: Session, actor: Actor, customer: Customer) -> dict[str, int]:
    """Removes the personal data of one customer; keeps non-personal data and invoices."""
    counts = {"photos": 0, "quotes": 0, "drafts": 0, "orders": 0, "addresses": 0}
    orders = customer_orders(db, customer.id)
    for o in orders:
        for p in list(db.scalars(select(Photo).where(Photo.order_id == o.id))):
            delete_photo(db, p)
            counts["photos"] += 1
        for q in list(db.scalars(select(Quote).where(Quote.order_id == o.id))):
            _delete_file(db, q.file_id)
            db.delete(q)
            counts["quotes"] += 1
        o.notes = None
        est = dict(o.estimate or {})
        est.pop("photo_check", None)
        o.estimate = est
        for ap in db.scalars(select(AccessPath).where(AccessPath.order_id == o.id)):
            ap.notes = None
            for s in db.scalars(select(PathSegment).where(PathSegment.path_id == ap.id)):
                s.notes = None
        for pl in db.scalars(select(Plant).where(Plant.order_id == o.id)):
            pl.notes = None
        for d in db.scalars(select(Deviation).where(Deviation.order_id == o.id)):
            d.note = None
            for pid in d.photo_ids or []:
                ph = db.get(Photo, uuid.UUID(pid))
                if ph is not None:
                    delete_photo(db, ph)
            d.photo_ids = []
        counts["orders"] += 1
    for d in list(db.scalars(select(Draft).where(Draft.customer_id == customer.id))):
        for p in list(db.scalars(select(Photo).where(Photo.draft_id == d.id))):
            delete_photo(db, p)
            counts["photos"] += 1
        d.source_text = ""
        d.extracted = {}
        d.follow_up = None
        counts["drafts"] += 1
    address_ids = []
    for a in db.scalars(select(Address).where(Address.customer_id == customer.id)):
        a.label = None
        a.street = ERASED
        a.lat = a.lon = None
        a.parking_notes = a.bell_notes = a.access_notes = None
        address_ids.append(a.id)
        counts["addresses"] += 1
    customer.name = ERASED
    for attr in ("company", "email", "phone", "notes", "consent_text"):
        if hasattr(customer, attr):
            setattr(customer, attr, None)
    customer.consent_photos = False
    if hasattr(customer, "deleted_at") and customer.deleted_at is None:
        customer.deleted_at = datetime.now(UTC)
    # personal values in the change log of this customer and its addresses
    ids = [str(customer.id), *[str(x) for x in address_ids]]
    for e in db.scalars(
        select(AuditLog).where(AuditLog.entity.in_(("customer", "address")), AuditLog.entity_id.in_(ids))
    ):
        e.old_value = {"erased": True} if e.old_value else None
        e.new_value = {"erased": True} if e.new_value else None
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=customer.tenant_id,
        entity="customer",
        entity_id=customer.id,
        action="erase",
        new=counts,
    )
    return counts


def run_retention(
    db: Session, actor: Actor, tenant_id: uuid.UUID, today: date | None = None
) -> dict[str, int]:
    r = SettingsResolver(db, tenant_id)
    now = datetime.combine(today or date.today(), datetime.min.time(), tzinfo=UTC)
    photo_cut = now - timedelta(days=int(r.get("privacy.photo_retention_days")))
    cust_cut = now - timedelta(days=int(r.get("privacy.customer_retention_days")))
    inv_cut = (today or date.today()).replace(
        year=(today or date.today()).year - int(r.get("privacy.invoice_retention_years"))
    )
    out = {"photos": 0, "customers": 0, "invoices": 0}
    # photos of finished or long untouched orders, and of drafts that never became an order
    rows = db.execute(
        select(Photo, PickupOrder)
        .outerjoin(PickupOrder, PickupOrder.id == Photo.order_id)
        .where(Photo.tenant_id == tenant_id, Photo.created_at < photo_cut)
    ).all()
    for p, o in rows:
        if o is None or o.status in FINISHED or (o.updated_at and o.updated_at < photo_cut):
            delete_photo(db, p)
            out["photos"] += 1
    # customers without activity
    for c in db.scalars(select(Customer).where(Customer.tenant_id == tenant_id, Customer.name != ERASED)):
        orders = customer_orders(db, c.id)
        last = max([c.updated_at or c.created_at, *[o.updated_at or o.created_at for o in orders]])
        active = any(o.status not in FINISHED and o.status != "draft" for o in orders)
        if last < cust_cut and not active:
            erase_customer(db, actor, c)
            out["customers"] += 1
    # customer invoices after the legal retention period
    for inv in list(
        db.scalars(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id, Invoice.kind == "customer", Invoice.issue_date < inv_cut
            )
        )
    ):
        _delete_file(db, inv.file_id)
        db.delete(inv)
        out["invoices"] += 1
    db.flush()
    if any(out.values()):
        audit.record(
            db, actor, tenant_id=tenant_id, entity="privacy", entity_id=None, action="retention", new=out
        )
    return out

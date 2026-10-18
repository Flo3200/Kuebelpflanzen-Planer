"""Privacy: export and erasure of a customer on request, automatic deletion after the retention periods,
tenant separation of these functions. (EXIF/GPS removal: test_phase2_intake.)"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import RlsContext, session_scope
from app.models.core import AuditLog
from app.models.formulas import Quote
from app.models.orders import Customer, Photo, PickupOrder, Plant, StoredFile
from app.models.platform import Invoice
from app.storage.backend import get_storage
from tests.helpers import make_photo


@pytest.fixture(scope="module")
def tenant():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[0])
    spec["slug"] = f"dsgvo-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Datenschutz Test", f"dsgvo-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo DS", f"dispo-ds-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(
        DemoOptions(seed=41, orders_per_tenant=8, tenants=[spec], measurements=False), reset=False
    )
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1]


@pytest.fixture
def owner(tenant, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(tenant[1], DEMO_PASSWORD)
    return api


def _order_with_customer(tid):
    with session_scope(RlsContext(tenant_id=tid)) as db:
        o = db.scalar(
            select(PickupOrder)
            .where(
                PickupOrder.tenant_id == tid,
                PickupOrder.deleted_at.is_(None),
                PickupOrder.estimate.isnot(None),
            )
            .order_by(PickupOrder.number)
        )
        return str(o.id), str(o.customer_id)


def test_export_and_erase_customer(owner, tenant, new_tenant):
    tid = tenant[0]
    order_id, customer_id = _order_with_customer(tid)
    # a photo, an offer and an invoice for this customer
    owner.post(
        "/api/photos",
        expect=201,
        files={"file": ("p.jpg", make_photo(), "image/jpeg")},
        data={"kind": "plant_front", "order_id": order_id, "consent_confirmed": "true"},
    )
    owner.post(f"/api/orders/{order_id}/quote", expect=201)
    inv = owner.post(f"/api/billing/orders/{order_id}/invoice", expect=201).json()
    with session_scope(RlsContext(tenant_id=tid)) as db:
        name = db.get(Customer, uuid.UUID(customer_id)).name
        photo_keys = [
            db.get(StoredFile, p.file_id).key
            for p in db.scalars(select(Photo).where(Photo.order_id == uuid.UUID(order_id)))
        ]
        n_plants = len(list(db.scalars(select(Plant).where(Plant.order_id == uuid.UUID(order_id)))))
    assert photo_keys and n_plants
    # export: everything in one ZIP
    r = owner.get(f"/api/customers/{customer_id}/export")
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    data = json.loads(z.read("daten.json"))
    assert data["customer"]["name"] == name and data["orders"] and data["orders"][0]["plants"]
    assert any(n.startswith("fotos/") for n in z.namelist()) and any(
        n.startswith("dokumente/") for n in z.namelist()
    )
    # another tenant cannot export or erase
    _t, other = new_tenant()
    other.get(f"/api/customers/{customer_id}/export", expect=404)
    other.post(f"/api/customers/{customer_id}/erase", json={"confirm": True}, expect=404)
    # erase needs an explicit confirmation
    owner.post(f"/api/customers/{customer_id}/erase", json={"confirm": False}, expect=400)
    res = owner.post(f"/api/customers/{customer_id}/erase", json={"confirm": True}).json()
    assert res["erased"]["photos"] >= 1 and res["erased"]["quotes"] >= 1
    with session_scope(RlsContext(tenant_id=tid)) as db:
        c = db.get(Customer, uuid.UUID(customer_id))
        assert c.name == "gelöscht" and c.email is None and c.phone is None and c.deleted_at is not None
        assert not list(db.scalars(select(Photo).where(Photo.order_id == uuid.UUID(order_id))))
        assert not list(db.scalars(select(Quote).where(Quote.order_id == uuid.UUID(order_id))))
        # not personal: plants stay (model data); invoices stay (retention obligation)
        assert len(list(db.scalars(select(Plant).where(Plant.order_id == uuid.UUID(order_id))))) == n_plants
        assert db.get(Invoice, uuid.UUID(inv["id"])) is not None
        logs = list(
            db.scalars(
                select(AuditLog).where(AuditLog.entity == "customer", AuditLog.entity_id == customer_id)
            )
        )
        assert all(name not in json.dumps([e.old_value, e.new_value], ensure_ascii=False) for e in logs)
    for key in photo_keys:
        with pytest.raises(FileNotFoundError):
            get_storage().get(key)


def test_retention_deletes_old_photos_customers_and_invoices(owner, tenant):
    tid = tenant[0]
    owner.put("/api/settings", json={"scope": "tenant", "key": "privacy.photo_retention_days", "value": 30})
    owner.put(
        "/api/settings", json={"scope": "tenant", "key": "privacy.customer_retention_days", "value": 60}
    )
    with session_scope(RlsContext(tenant_id=tid)) as db:
        orders = list(
            db.scalars(
                select(PickupOrder)
                .where(PickupOrder.tenant_id == tid, PickupOrder.deleted_at.is_(None))
                .order_by(PickupOrder.number)
            )
        )
        finished, active = orders[-1], orders[-2]
    for o in (finished, active):
        owner.post(
            "/api/photos",
            expect=201,
            files={"file": ("p.jpg", make_photo(), "image/jpeg")},
            data={"kind": "plant_front", "order_id": str(o.id), "consent_confirmed": "true"},
        )
    old = datetime.now(UTC) - timedelta(days=400)
    with session_scope(RlsContext(tenant_id=tid)) as db:
        for p in db.scalars(select(Photo).where(Photo.order_id.in_([finished.id, active.id]))):
            p.created_at = old
        f = db.get(PickupOrder, finished.id)
        f.status = "returned"
        # the customer of the finished order has had no activity for a long time
        c = db.get(Customer, f.customer_id)
        others = list(db.scalars(select(PickupOrder).where(PickupOrder.customer_id == c.id)))
        db.flush()
        from sqlalchemy import update

        db.execute(
            update(PickupOrder)
            .where(PickupOrder.customer_id == c.id)
            .values(updated_at=old, created_at=old, status="returned")
        )
        db.execute(update(Customer).where(Customer.id == c.id).values(updated_at=old, created_at=old))
        db.add(
            Invoice(
                tenant_id=tid,
                kind="customer",
                number="R-2010-0001",
                issue_date=date(2010, 3, 1),
                lines=[],
                issuer={},
                recipient={},
            )
        )
        finished_customer = c.id
        assert others
    res = owner.post("/api/privacy/retention", json={"sync": True}).json()
    assert res["status"] == "done", res
    out = res["result"]
    assert out["photos"] >= 1 and out["customers"] >= 1 and out["invoices"] == 1
    with session_scope(RlsContext(tenant_id=tid)) as db:
        assert not list(db.scalars(select(Photo).where(Photo.order_id == finished.id)))
        # the active order keeps its photo although it is old
        assert list(db.scalars(select(Photo).where(Photo.order_id == active.id)))
        assert db.get(Customer, finished_customer).name == "gelöscht"
        assert (
            db.scalar(select(Invoice).where(Invoice.number == "R-2010-0001", Invoice.tenant_id == tid))
            is None
        )

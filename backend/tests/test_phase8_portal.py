"""Phase 8, part 2: customer portal (login by personal link, own orders only, consent, guided photos,
location, offer acceptance, return wish, online payment with the test provider and Stripe)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.db import RlsContext, session_scope
from app.models.orders import Address, Customer, Photo, PickupOrder
from app.models.platform import Invoice, Payment
from app.payments.providers import StripeProvider, verify_stripe_signature
from tests.helpers import make_photo, set_modules


@pytest.fixture(scope="module")
def demo():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[1])
    spec["slug"] = f"portal-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Portal Test", f"portal-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Portal", f"dispo-portal-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(
        DemoOptions(seed=61, orders_per_tenant=14, tenants=[spec], measurements=False), reset=False
    )
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1]


@pytest.fixture
def owner(demo, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(demo[1], DEMO_PASSWORD)
    set_modules(api, portal=True, customer_billing=True, payments=True)
    return api


def _two_customers(tid):
    with session_scope(RlsContext(tenant_id=tid)) as db:
        rows = list(
            db.scalars(
                select(PickupOrder)
                .where(
                    PickupOrder.tenant_id == tid,
                    PickupOrder.direction == "pickup",
                    PickupOrder.deleted_at.is_(None),
                )
                .order_by(PickupOrder.number)
            )
        )
        seen, out = set(), []
        for o in rows:
            if o.customer_id not in seen:
                seen.add(o.customer_id)
                out.append((str(o.customer_id), str(o.id)))
        return out[0], out[1]


def portal_client(make_client, owner, customer_id):
    link = owner.post(f"/api/customers/{customer_id}/portal-link").json()
    assert "/kunde/login/" in link["url"]
    c = make_client()
    c.post(f"/api/auth/customer/{link['code']}")
    return c


def test_customer_sees_only_own_orders_and_no_staff_api(demo, owner, make_client):
    (cid, oid), (other_cid, other_oid) = _two_customers(demo[0])
    c = portal_client(make_client, owner, cid)
    me = c.get("/api/portal/me").json()
    assert me["customer"]["id"] == cid and me["tenant"]["name"]
    orders = c.get("/api/portal/orders").json()
    assert orders and all(o["id"] != other_oid for o in orders)
    assert any(o["id"] == oid for o in orders)
    detail = c.get(f"/api/portal/orders/{oid}").json()
    assert detail["plants"] and detail["progress"]["steps"][0] == "request"
    # foreign order, staff endpoints and settings are closed
    c.get(f"/api/portal/orders/{other_oid}", expect=404)
    for url in ("/api/orders", "/api/settings", "/api/customers", f"/api/orders/{oid}", "/api/plans"):
        c.get(url, expect=403)
    # an invalid link does not log in
    anon = make_client()
    anon.post("/api/auth/customer/falsch", expect=401)


def test_consent_photos_location(demo, owner, make_client):
    (cid, oid), _ = _two_customers(demo[0])
    c = portal_client(make_client, owner, cid)
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        db.get(Customer, uuid.UUID(cid)).consent_photos = False
    plant = c.get(f"/api/portal/orders/{oid}").json()["plants"][0]
    files = {"file": ("f.jpg", make_photo(), "image/jpeg")}
    r = c.post(
        f"/api/portal/orders/{oid}/photos",
        files=files,
        data={"kind": "plant_front", "plant_id": plant["id"]},
        expect=409,
    )
    assert r.json()["error"]["code"] == "errors.consent_required"
    c.post("/api/portal/consent", json={"accept": True})
    ph = c.post(
        f"/api/portal/orders/{oid}/photos",
        expect=201,
        files={"file": ("f.jpg", make_photo(gps=True), "image/jpeg")},
        data={"kind": "plant_front", "plant_id": plant["id"]},
    ).json()
    after = c.get(f"/api/portal/orders/{oid}").json()
    p2 = next(p for p in after["plants"] if p["id"] == plant["id"])
    assert "plant_front" not in p2["missing"] and any(x["id"] == ph["id"] for x in p2["photos"])
    # the customer can open own photos, but not photos of other customers
    assert c.get(ph["url"]).content[:2] == b"\xff\xd8"
    _o, (other_cid, other_oid) = _two_customers(demo[0])
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        foreign = db.scalar(select(Photo).where(Photo.order_id == uuid.UUID(other_oid)))
    if foreign is None:
        foreign_url = owner.post(
            "/api/photos",
            expect=201,
            files={"file": ("x.jpg", make_photo(), "image/jpeg")},
            data={"kind": "pot", "order_id": other_oid, "consent_confirmed": "true"},
        ).json()["url"]
    else:
        foreign_url = f"/api/files/{foreign.file_id}"
    c.get(foreign_url, expect=404)
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        assert db.get(Customer, uuid.UUID(cid)).consent_at is not None
    # location pin and hints
    c.put(
        f"/api/portal/orders/{oid}/location",
        json={"lat": 48.7, "lon": 9.15, "parking_notes": "Einfahrt frei halten"},
    )
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        a = db.get(Address, db.get(PickupOrder, uuid.UUID(oid)).address_id)
        assert (a.lat, a.lon, a.geocode_source, a.parking_notes) == (
            48.7,
            9.15,
            "customer",
            "Einfahrt frei halten",
        )


def test_accept_quote_confirms_order(demo, owner, make_client):
    (cid, oid), _ = _two_customers(demo[0])
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        db.get(PickupOrder, uuid.UUID(oid)).status = "draft"
    q = owner.post(f"/api/orders/{oid}/quote", expect=201).json()
    c = portal_client(make_client, owner, cid)
    view = c.get(f"/api/portal/orders/{oid}").json()
    assert view["progress"]["current"] == "offer" and view["quotes"][0]["id"] == q["id"]
    assert c.get(view["quotes"][0]["pdf_url"]).content[:4] == b"%PDF"
    r = c.post(f"/api/portal/quotes/{q['id']}/accept").json()
    assert r == {"status": "accepted", "order_status": "confirmed"}
    c.post(f"/api/portal/quotes/{q['id']}/accept", expect=409)


def test_return_wish_is_used_for_the_return(demo, owner, make_client):
    (cid, oid), _ = _two_customers(demo[0])
    c = portal_client(make_client, owner, cid)
    c.put(
        f"/api/portal/orders/{oid}/return-wish",
        json={"earliest_date": "2027-05-03", "latest_date": "2027-05-14", "notes": "nicht vor 10 Uhr"},
    )
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        db.get(PickupOrder, uuid.UUID(oid)).status = "stored"
    owner.post("/api/orders/returns", json={"earliest_date": "2027-04-01", "order_ids": [oid]})
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        ret = db.scalar(select(PickupOrder).where(PickupOrder.return_of_id == uuid.UUID(oid)))
        assert str(ret.earliest_date) == "2027-05-03" and str(ret.latest_date) == "2027-05-14"
        assert "nicht vor 10 Uhr" in (ret.notes or "")
    # the return shows up in the portal as well
    assert any(o["direction"] == "return" for o in c.get("/api/portal/orders").json())


def test_online_payment_with_test_provider(demo, owner, make_client):
    (cid, oid), _ = _two_customers(demo[0])
    c = portal_client(make_client, owner, cid)
    inv = owner.post(f"/api/billing/orders/{oid}/invoice", expect=201).json()
    r = c.post(
        "/api/portal/payments", json={"invoice_id": inv["id"]}, expect=409
    )  # payments are off by default
    assert r.json()["error"]["code"] == "errors.module_off"
    owner.put("/api/settings", json={"scope": "tenant", "key": "payments.provider", "value": "test"})
    try:
        p = c.post("/api/portal/payments", expect=201, json={"invoice_id": inv["id"]}).json()
        assert (
            p["status"] == "pending"
            and p["checkout_url"] == f"/kunde/zahlung/{p['id']}"
            and p["amount"] == inv["gross"]
        )
        paid = c.post(f"/api/portal/payments/{p['id']}/simulate", json={"success": True}).json()
        assert paid["status"] == "paid"
        with session_scope(RlsContext(tenant_id=demo[0])) as db:
            i = db.get(Invoice, uuid.UUID(inv["id"]))
            assert i.status == "paid" and i.payment_provider == "test" and i.paid_at is not None
        c.post("/api/portal/payments", json={"invoice_id": inv["id"]}, expect=409)  # nothing left to pay
        assert any(
            x["id"] == p["id"] and x["status"] == "paid"
            for x in owner.get("/api/payments", params={"order_id": oid}).json()
        )
    finally:
        owner.put("/api/settings", json={"scope": "tenant", "key": "payments.provider", "value": "off"})


def _sign(body: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_signature_and_checkout_request(monkeypatch):
    body = b'{"id":"evt_1"}'
    assert verify_stripe_signature(body, _sign(body, "whsec_x"), "whsec_x")
    assert not verify_stripe_signature(body, _sign(body, "whsec_other"), "whsec_x")
    assert not verify_stripe_signature(body, _sign(body, "whsec_x", ts=int(time.time()) - 3600), "whsec_x")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["account"] = request.headers.get("Stripe-Account")
        seen["body"] = request.content.decode()
        return httpx.Response(
            200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}
        )

    from app.core import config

    monkeypatch.setattr(config.get_config(), "stripe_secret_key", "sk_test_x")
    co = StripeProvider(transport=httpx.MockTransport(handler)).create_checkout(
        "pid-1", 91.5, "Rechnung R-1", "https://ok", "https://no", "acct_123"
    )
    assert co.provider_ref == "cs_test_1" and co.url.startswith("https://checkout.stripe.com/")
    assert seen["path"] == "/v1/checkout/sessions" and seen["account"] == "acct_123"
    assert "unit_amount%5D=9150" in seen["body"] and "metadata%5Bpayment_id%5D=pid-1" in seen["body"]


def test_stripe_webhook_marks_paid(demo, owner, make_client, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_config(), "stripe_webhook_secret", "whsec_test")
    (cid, oid), _ = _two_customers(demo[0])
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        p = Payment(
            tenant_id=demo[0],
            customer_id=uuid.UUID(cid),
            order_id=uuid.UUID(oid),
            amount_eur=10,
            provider="stripe",
            status="pending",
            provider_ref="cs_x",
        )
        db.add(p)
        db.flush()
        pid = str(p.id)
    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "payment_status": "paid", "metadata": {"payment_id": pid}}},
    }
    body = json.dumps(event).encode()
    anon = make_client()
    bad = anon.c.post("/api/payments/stripe/webhook", content=body, headers={"Stripe-Signature": "t=1,v1=00"})
    assert bad.status_code == 400
    ok = anon.c.post(
        "/api/payments/stripe/webhook", content=body, headers={"Stripe-Signature": _sign(body, "whsec_test")}
    )
    assert ok.status_code == 200
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        assert db.get(Payment, uuid.UUID(pid)).status == "paid"

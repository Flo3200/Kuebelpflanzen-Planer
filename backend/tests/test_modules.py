"""Logistics focus (package A): optional modules are off for a new tenant and can be switched on."""

from __future__ import annotations

import pytest

from tests.helpers import set_modules
from tests.test_phase3_estimates import make_order


def test_new_tenant_has_only_logistics(new_tenant):
    _, owner = new_tenant()
    me = owner.get("/api/auth/me").json()
    assert me["modules"] == {"storage": False, "customer_billing": False, "portal": False, "payments": False}
    dash = owner.get("/api/dashboard").json()
    assert dash["storage"] is None and dash["revenue_quoted"] is None
    # settings of switched-off modules are marked (the settings page hides them), the switches are not
    vals = {v["key"]: v for v in owner.get("/api/settings", params={"scope": "tenant"}).json()["values"]}
    assert all(
        vals[f"modules.{m}"]["module_active"] for m in ("storage", "customer_billing", "portal", "payments")
    )
    for key in ("general.storage_warn_pct", "pricing.base_price", "portal.link_days", "payments.provider"):
        assert vals[key]["module_active"] is False
    keys = {k for k, v in vals.items() if v["module_active"]}
    # drive share of the cost estimate stays (it is a cost, not a price)
    assert "pricing.typical_tour_stops" in keys


def test_storage_module_off_and_on(new_tenant):
    _, owner = new_tenant()
    owner.get("/api/storage-areas", expect=409)
    owner.post("/api/storage-areas", expect=409, json={"name": "Halle"})
    owner.get("/api/storage/occupancy", expect=409)
    plant_meta = {f["name"]: f for f in owner.get("/api/meta/entities/plant").json()["fields"]}
    assert plant_meta["storage_area_id"]["module"] == "storage"

    set_modules(owner, storage=True)
    area = owner.post("/api/storage-areas", expect=201, json={"name": "Halle", "area_m2": 80}).json()
    assert owner.get("/api/storage/occupancy").json()["capacity_m2"] == 80
    assert owner.get("/api/dashboard").json()["storage"]["capacity_m2"] == 80
    vals = {v["key"]: v for v in owner.get("/api/settings", params={"scope": "tenant"}).json()["values"]}
    assert vals["general.storage_warn_pct"]["module_active"] is True
    # switching off again hides it, the data stays
    set_modules(owner, storage=False)
    owner.get(f"/api/storage-areas/{area['id']}", expect=409)
    set_modules(owner, storage=True)
    assert owner.get(f"/api/storage-areas/{area['id']}").json()["name"] == "Halle"


def test_customer_billing_module_off_and_on(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=30, plants=2)
    owner.post(f"/api/orders/{oid}/quote", expect=409)
    owner.get(f"/api/orders/{oid}/quotes", expect=409)
    owner.post(f"/api/billing/orders/{oid}/invoice", expect=409)
    owner.get("/api/billing/invoices", expect=409, params={"kind": "customer"})
    owner.get("/api/pricing/overview", expect=409)
    # the platform invoices of the tenant are not part of the module
    owner.get("/api/billing/invoices", params={"kind": "platform"})
    # the logistics costs are always there
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est["costs"]["self_cost"] > 0

    set_modules(owner, customer_billing=True)
    owner.post(f"/api/orders/{oid}/quote", expect=201)
    assert len(owner.get(f"/api/orders/{oid}/quotes").json()) == 1
    owner.get("/api/pricing/overview")
    assert owner.get("/api/dashboard").json()["revenue_quoted"] is not None


def test_portal_and_payments_modules(new_tenant, make_client):
    _, owner = new_tenant()
    c = owner.post("/api/customers", expect=201, json={"name": "Frau Linde", "phone": "0711 1"}).json()
    owner.post(f"/api/customers/{c['id']}/portal-link", expect=409)

    set_modules(owner, portal=True)
    link = owner.post(f"/api/customers/{c['id']}/portal-link").json()
    cust = make_client()
    cust.post(f"/api/auth/customer/{link['code']}")
    me = cust.get("/api/portal/me").json()
    assert me["payments"] == "off" and me["modules"] == {"customer_billing": False, "payments": False}
    cust.post("/api/portal/payments", expect=409, json={"invoice_id": None})

    # payments need the portal: switching the portal off closes the portal and payments
    set_modules(owner, payments=True)
    assert owner.get("/api/auth/me").json()["modules"]["payments"] is True
    set_modules(owner, portal=False)
    assert owner.get("/api/auth/me").json()["modules"]["payments"] is False
    cust.get("/api/portal/me", expect=409)


@pytest.mark.parametrize(
    ("entity", "advanced", "basic"),
    [
        ("customer", {"company", "email", "preferred_contact", "notes"}, {"name", "phone"}),
        (
            "vehicle",
            {"plate", "loading_edge_cm", "has_ramp", "has_lift", "notes"},
            {"payload_kg", "door_width_cm"},
        ),
        ("staff", {"phone", "email", "short_name", "qualifications"}, {"name", "licences"}),
        ("plant", {"not_stackable", "required_equipment", "notes"}, {"weight_kg", "pot_diameter_cm"}),
    ],
)
def test_fields_without_calculation_are_folded(new_tenant, entity, advanced, basic):
    _, owner = new_tenant()
    meta = {f["name"]: f for f in owner.get(f"/api/meta/entities/{entity}").json()["fields"]}
    assert all(meta[n]["advanced"] for n in advanced)
    assert not any(meta[n]["advanced"] for n in basic)

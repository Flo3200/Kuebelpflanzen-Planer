"""Package E: own cost items change tour and order costs; costs are pure logistics costs."""

from __future__ import annotations

import pytest

from tests.test_phase3_estimates import make_order
from tests.test_teams import MONDAY, _order


def test_defaults_are_logistics_only(new_tenant):
    _, owner = new_tenant()
    vals = {v["key"]: v for v in owner.get("/api/settings", params={"scope": "tenant"}).json()["values"]}
    assert vals["costs.overhead_pct"]["value"] == 0 and vals["costs.margin_pct"]["value"] == 0
    oid = make_order(owner, weight=30, plants=2)
    costs = owner.get(f"/api/orders/{oid}/estimate").json()["costs"]
    parts = costs["labour"] + costs["drive_labour"] + costs["vehicle"] + costs["equipment"] + costs["custom"]
    assert costs["self_cost"] == pytest.approx(parts, abs=0.02)  # no overhead on top


def test_own_cost_item_changes_order_estimate(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=30, plants=3)
    before = owner.get(f"/api/orders/{oid}/estimate").json()["costs"]
    item = owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Entsorgung Erde", "amount_eur": 2.5, "basis": "per_plant"},
    ).json()
    after = owner.get(f"/api/orders/{oid}/estimate").json()["costs"]
    assert after["custom"] == pytest.approx(7.5)
    assert after["self_cost"] == pytest.approx(before["self_cost"] + 7.5, abs=0.02)
    assert after["custom_items"] == [
        {"id": item["id"], "name": "Entsorgung Erde", "basis": "per_plant", "scope": "tenant", "amount": 7.5}
    ]
    # an item belongs to the nursery, one vehicle or one person, not to two at once
    staff = owner.post("/api/staff", expect=201, json={"name": "Mia", "licences": ["B"]}).json()
    van = owner.post("/api/vehicles", expect=201, json={"name": "Van"}).json()
    owner.post(
        "/api/cost-items",
        expect=400,
        json={
            "name": "x",
            "amount_eur": 1,
            "basis": "per_day",
            "vehicle_id": van["id"],
            "staff_id": staff["id"],
        },
    )


def test_own_cost_items_in_tour_costs(new_tenant):
    _, owner = new_tenant()
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    staff = [
        owner.post("/api/staff", expect=201, json={"name": f"Person {i}", "licences": ["B"]}).json()
        for i in range(2)
    ]
    van = owner.post("/api/vehicles", expect=201, json={"name": "Transporter"}).json()
    owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Maut", "amount_eur": 0.2, "basis": "per_km", "vehicle_id": van["id"]},
    )
    owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Leasing", "amount_eur": 420, "basis": "per_month", "vehicle_id": van["id"]},
    )
    owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Spesen", "amount_eur": 14, "basis": "per_day", "staff_id": staff[0]["id"]},
    )
    owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Nicht mehr", "amount_eur": 99, "basis": "per_use", "active": False},
    )
    for w in (15, 20):
        _order(owner, w)
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(MONDAY), "days": 2, "sync": True, "pack": False}
    ).json()
    plan = owner.get(f"/api/plans/{p['id']}").json()
    assert plan["tours"], plan["unassigned"]
    tour = plan["tours"][0]
    c = tour["costs"]
    items = {x["name"]: x["amount"] for x in c["custom_items"]}
    assert items["Maut"] == pytest.approx(0.2 * tour["distance_km"], abs=0.02)
    if tour["trip_no"] == 1:
        assert items["Leasing"] == pytest.approx(20.0)  # 420 € / 21 working days
        assert items["Spesen"] == pytest.approx(14.0)
    assert "Nicht mehr" not in items
    assert c["custom"] == pytest.approx(sum(items.values()), abs=0.02)
    assert c["self_cost"] == pytest.approx(c["labour"] + c["vehicle"] + c["overtime"] + c["custom"], abs=0.02)
    # the stops carry their share, so the order costs after planning include the own costs
    stop_custom = sum(s["costs"].get("custom", 0) for s in tour["stops"])
    assert stop_custom == pytest.approx(c["custom"], abs=0.05)
    owner.post(f"/api/plans/{p['id']}/activate")
    order = owner.get(f"/api/orders/{tour['stops'][0]['order_id']}").json()["order"]
    assert order["estimate"]["plan_costs"]["custom"] > 0

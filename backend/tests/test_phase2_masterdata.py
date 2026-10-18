"""Phase 2: master data, species overrides, availability, tenant separation of new tables."""

from __future__ import annotations

import uuid
from datetime import date, timedelta


def test_staff_vehicle_equipment_crud_and_isolation(new_tenant):
    _, a = new_tenant()
    _, b = new_tenant()
    s = a.post("/api/staff", expect=201, json={"name": "Ali Kaya", "licences": ["B", "BE"]}).json()
    v = a.post(
        "/api/vehicles", expect=201, json={"name": "Sprinter 1", "plate": "S-GF 101", "kind": "van"}
    ).json()
    a.put(
        f"/api/vehicles/{v['id']}/shelves",
        json={
            "shelves": [
                {
                    "name": "Regal links",
                    "x_cm": 0,
                    "y_cm": 0,
                    "length_cm": 150,
                    "depth_cm": 40,
                    "height_cm": 100,
                    "clearance_cm": 70,
                    "max_load_kg": 60,
                }
            ]
        },
    )
    assert len(a.get("/api/shelves", params={"filter": f"vehicle_id={v['id']}"}).json()) == 1
    e = a.post(
        "/api/equipment",
        expect=201,
        json={
            "name": "Sackkarre",
            "kind": "hand_truck",
            "capacity_kg": 150,
            "solo_limit_kg": 80,
            "carry_time_factor": 0.8,
            "vehicle_id": v["id"],
        },
    ).json()
    assert e["vehicle_id"] == v["id"]
    # object-level settings of a person
    a.put(
        "/api/settings",
        json={"scope": "staff", "object_id": s["id"], "key": "staff.solo_carry_kg", "value": 35},
    )
    vals = a.get("/api/settings", params={"scope": "staff", "object_id": s["id"]}).json()["values"]
    assert next(x for x in vals if x["key"] == "staff.solo_carry_kg")["origin"] == "staff"
    # tenant B sees nothing of A and cannot reference A's vehicle
    assert b.get("/api/staff").json() == []
    b.get(f"/api/vehicles/{v['id']}", expect=404)
    b.post("/api/equipment", expect=400, json={"name": "fremd", "vehicle_id": v["id"]})
    b.patch(f"/api/staff/{s['id']}", json={"name": "x"}, expect=404)
    # delete is soft and logged
    a.delete(f"/api/staff/{s['id']}")
    assert a.get("/api/staff").json() == []
    assert any(
        e["entity"] == "staff" and e["action"] == "delete" for e in a.get("/api/audit").json()["items"]
    )


def test_species_knowledge_base_is_admin_only(admin, new_tenant):
    _, a = new_tenant()
    olive = next(s for s in admin.get("/api/species").json() if s["name"] == "Olivenbaum")
    assert olive["is_global"]
    # since package B tenants no longer see or change species (the plant carries the values)
    a.get("/api/species", expect=403)
    a.patch(f"/api/species/{olive['id']}", expect=403, json={"plant_kg_per_l": 0.05})
    a.delete(f"/api/species/{olive['id']}", expect=403)
    # the admin maintains the knowledge base
    upd = admin.patch(f"/api/species/{olive['id']}", json={"notes": "geprüft"}).json()
    assert upd["notes"] == "geprüft" and upd["id"] == olive["id"]


def test_availability_calendar(new_tenant):
    _, a = new_tenant()
    s = a.post("/api/staff", expect=201, json={"name": "Mara"}).json()
    monday = date(2026, 10, 19)
    a.post(
        "/api/availability",
        expect=201,
        json={
            "resource_type": "staff",
            "resource_id": s["id"],
            "kind": "vacation",
            "date_from": str(monday + timedelta(days=1)),
            "date_to": str(monday + timedelta(days=2)),
        },
    )
    a.post(
        "/api/availability",
        expect=201,
        json={
            "resource_type": "staff",
            "resource_id": s["id"],
            "kind": "unavailable",
            "date_from": str(monday + timedelta(days=3)),
            "date_to": str(monday + timedelta(days=3)),
            "start_time": "07:00",
            "end_time": "12:00",
        },
    )
    cal = a.get("/api/availability-calendar", params={"start": str(monday), "days": 7}).json()
    days = cal["staff"][0]["days"]
    assert days[str(monday)]["available"] and days[str(monday)]["start"] == "07:00"
    assert not days[str(monday + timedelta(days=1))]["available"]
    assert days[str(monday + timedelta(days=1))]["reason"] == "vacation"
    assert days[str(monday + timedelta(days=3))]["start"] == "12:00"
    assert not days[str(monday + timedelta(days=5))]["available"]  # saturday


def test_orders_plants_paths_and_estimates(new_tenant):
    _, a = new_tenant()
    c = a.post("/api/customers", expect=201, json={"name": "Familie Graf"}).json()
    addr = a.post(
        "/api/addresses",
        expect=201,
        json={
            "customer_id": c["id"],
            "street": "Lindenweg 4",
            "postal_code": "70199",
            "city": "Stuttgart",
            "lat": 48.76,
            "lon": 9.15,
        },
    ).json()
    o = a.post("/api/orders", expect=201, json={"customer_id": c["id"], "address_id": addr["id"]}).json()
    oid = o["order"]["id"]
    assert o["order"]["number"].startswith("A-")
    p = a.post(
        f"/api/orders/{oid}/plants",
        expect=201,
        json={"species_name": "Olivenbaum", "pot_diameter_cm": 60, "pot_height_cm": 55},
    ).json()
    # weight is estimated from pot volume and species; plausible range for a 60 cm pot
    assert 90 < p["weight_kg"] < 250, p["weight_kg"]
    assert "weight_kg" in p["estimated_fields"] and "crown_width_cm" in p["estimated_fields"]
    assert p["weight_uncertainty_kg"] > 0
    # changing the pot recomputes the estimated weight; entered values are no longer estimates
    p2 = a.patch(f"/api/plants/{p['id']}", json={"pot_diameter_cm": 40, "pot_height_cm": 35}).json()
    assert p2["weight_kg"] < p["weight_kg"]
    assert "pot_diameter_cm" not in p2["estimated_fields"]
    path = a.post(f"/api/orders/{oid}/paths", expect=201, json={"name": "Garten"}).json()
    res = a.put(
        f"/api/paths/{path['id']}/segments",
        json={
            "segments": [
                {"kind": "flat", "length_m": 12, "surface": "gravel"},
                {"kind": "stairs", "length_m": 4, "steps": 12, "height_diff_m": 2.0, "min_width_cm": 95},
                {"kind": "door", "length_m": 1, "doors": 1, "min_width_cm": 80},
            ]
        },
    ).json()
    assert res["summary"] == {
        **res["summary"],
        "length_m": 17,
        "steps": 12,
        "min_width_cm": 80,
        "has_stairs": True,
    }
    detail = a.get(f"/api/orders/{oid}").json()
    assert detail["plants"][0]["access_path_id"] == path["id"]
    # spring return reuses plants
    ret = a.post(f"/api/orders/{oid}/return", expect=201).json()
    assert ret["order"]["direction"] == "return" and len(ret["plants"]) == 1
    assert ret["order"]["number"].startswith("R-")
    # cancelling sets the timestamp
    a.patch(f"/api/orders/{oid}", json={"status": "cancelled"})
    assert a.get(f"/api/orders/{oid}").json()["order"]["cancelled_at"]
    assert a.get("/api/orders", params={"status": ["cancelled"]}).json()[0]["id"] == oid


def test_meta_fields_for_generated_forms(new_tenant):
    _, a = new_tenant()
    meta = a.get("/api/meta/entities/vehicle").json()
    f = {x["name"]: x for x in meta["fields"]}
    assert f["cargo_length_cm"]["unit"] == "cm" and f["cargo_length_cm"]["label"] != "cargo_length_cm"
    assert f["kind"]["enum"] == ["van", "truck", "trailer", "car"]
    assert meta["settings_scope"] == "vehicle"
    assert str(uuid.uuid4())

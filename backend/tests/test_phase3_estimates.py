"""Phase 3 acceptance: every order shows duration, labour time, team size and price;
a changed formula takes effect immediately."""

from __future__ import annotations

import math

import pytest


def make_order(api, *, weight=50.0, path_length=15.0, plants=1, stairs: int = 0, lat=48.80, lon=9.30):
    c = api.post("/api/customers", expect=201, json={"name": "Testkunde"}).json()
    a = api.post(
        "/api/addresses",
        expect=201,
        json={
            "customer_id": c["id"],
            "street": "Teststraße 1",
            "postal_code": "70000",
            "city": "Stuttgart",
            "lat": lat,
            "lon": lon,
        },
    ).json()
    o = api.post("/api/orders", expect=201, json={"customer_id": c["id"], "address_id": a["id"]}).json()[
        "order"
    ]
    path = api.post(f"/api/orders/{o['id']}/paths", expect=201, json={"name": "Weg"}).json()
    segs = [{"kind": "flat", "length_m": path_length, "surface": "paved"}]
    if stairs:
        segs.append({"kind": "stairs", "length_m": 0.0, "steps": stairs, "height_diff_m": stairs * 0.17})
    api.put(f"/api/paths/{path['id']}/segments", json={"segments": segs})
    for _ in range(plants):
        api.post(
            f"/api/orders/{o['id']}/plants",
            expect=201,
            json={
                "pot_diameter_cm": 40,
                "pot_height_cm": 35,
                "total_height_cm": 150,
                "crown_width_cm": 60,
                "weight_kg": weight,
            },
        )
    return o["id"]


def test_start_formula_numbers(new_tenant):
    t, owner = new_tenant()
    oid = make_order(owner, weight=20, path_length=15)
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    # defaults: a0=6, a1=0.08, k_height=0.5, walk_speed=25, t_fixed=10; 20 kg -> 1 person
    work = (6 + 0.08 * 20) * (15 / 25 + 0.5 * 0) * 1 * 1
    assert est["team_size"] == 1
    assert est["plants"][0]["work"] == pytest.approx(work, abs=0.01)
    assert est["duration_min"] == pytest.approx(10 + work, abs=0.1)
    assert est["labour_min"] == pytest.approx(est["duration_min"] * 1, abs=0.1)
    # planning buffer: 80 % quantile with sigma 0.25
    factor = math.exp(0.8416212335729143 * 0.25)
    assert est["planning_duration_min"] == pytest.approx(est["duration_min"] * factor, abs=0.2)
    # one plant: a second person does not help (max_plants(work / crew) dominates)
    by_team = {int(k): v for k, v in est["durations_by_team"].items()}
    assert by_team[2] == by_team[1]
    # three plants: shorter with a larger team, but more labour time
    est3 = owner.get(f"/api/orders/{make_order(owner, weight=20, path_length=15, plants=3)}/estimate").json()
    by_team = {int(k): v for k, v in est3["durations_by_team"].items()}
    assert by_team[2] < by_team[1] and by_team[2] * 2 > by_team[1]


def test_duration_and_labour_with_team(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=60, path_length=20, plants=2, stairs=18)
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est["team_size"] == 4  # 60 kg -> 3 persons, +1 for stairs
    assert est["labour_min"] == pytest.approx(est["duration_min"] * 4, abs=0.2)
    assert all("stairs" in p["reasons"] for p in est["plants"])
    assert est["price"]["gross"] > 0 and est["costs"]["self_cost"] > 0
    assert est["price"]["coverage_pct"] is not None


def test_price_rules(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=10, path_length=3)
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est["price"]["gross"] == 49.0  # minimum price
    owner.put("/api/settings", json={"scope": "tenant", "key": "pricing.minimum_price", "value": 0})
    owner.put("/api/settings", json={"scope": "tenant", "key": "pricing.distance_mode", "value": "off"})
    owner.put("/api/settings", json={"scope": "tenant", "key": "pricing.rounding", "value": 0})
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    expected = 25 + 0.75 * est["labour_min"] + 6 * 1
    assert est["price"]["gross"] == pytest.approx(expected, abs=0.01)
    assert est["price"]["net"] == pytest.approx(expected / 1.19, abs=0.01)
    # customer-specific base price (object level of the hierarchy)
    order = owner.get(f"/api/orders/{oid}").json()
    owner.put(
        "/api/settings",
        json={
            "scope": "customer",
            "object_id": order["customer"]["id"],
            "key": "pricing.base_price",
            "value": 100,
        },
    )
    est2 = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est2["price"]["gross"] == pytest.approx(expected + 75, abs=0.01)
    # zones: depot of the test tenant is in Stuttgart (48.78, 9.18); order ~ 10 km away
    owner.put("/api/settings", json={"scope": "tenant", "key": "pricing.distance_mode", "value": "zones"})
    owner.put(
        "/api/settings",
        json={
            "scope": "tenant",
            "key": "pricing.zones",
            "value": [{"max_km": 5, "surcharge": 0}, {"max_km": 100, "surcharge": 20}],
        },
    )
    est3 = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est3["price"]["distance_surcharge"] == 20


def test_changed_formula_takes_effect_immediately(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=30, path_length=10)
    before = owner.get(f"/api/orders/{oid}").json()["order"]
    assert before["estimate"]["duration_min"] > 0 and before["price_quoted"] > 0
    formulas = owner.get("/api/formulas", params={"key": "time"}).json()["formulas"]
    tier1 = next(f for f in formulas if f["tier"] == 1 and f["is_global"])
    active = next(v for v in tier1["versions"] if v["id"] == tier1["active_version_id"])
    exprs = [dict(e) for e in active["expressions"]]
    for e in exprs:
        if e["name"] == "duration":
            e["expr"] = "t_fixed + 30 + max(sum_plants(work) / team, max_plants(work / crew)) / speed"
    r = owner.post(
        f"/api/formulas/{tier1['id']}/versions",
        expect=201,
        json={"expressions": exprs, "parameters": active["parameters"], "note": "Testaufschlag"},
    ).json()
    # a tenant editing the global formula gets its own override
    assert r["formula"]["tenant_id"] is not None and r["formula"]["overrides_id"] == tier1["id"]
    after = owner.get(f"/api/orders/{oid}").json()["order"]
    assert after["estimate"]["duration_min"] == pytest.approx(
        before["estimate"]["duration_min"] + 30, abs=0.1
    )
    assert after["estimate"]["formula"]["time"]["tenant_override"] is True
    # other tenants still use the global formula; resetting removes the override
    owner.delete(f"/api/formulas/{r['formula']['id']}")
    reset = owner.get(f"/api/orders/{oid}/estimate").json()
    assert reset["duration_min"] == pytest.approx(before["estimate"]["duration_min"], abs=0.1)


def test_invalid_formula_is_rejected_with_position(new_tenant):
    _, owner = new_tenant()
    tier1 = next(
        f for f in owner.get("/api/formulas", params={"key": "time"}).json()["formulas"] if f["tier"] == 1
    )
    bad = [
        {"name": "work", "level": "plant", "expr": "a0 + * weight"},
        {"name": "duration", "level": "stop", "expr": "t_fixed"},
    ]
    r = owner.post(
        f"/api/formulas/{tier1['id']}/versions",
        expect=400,
        json={"expressions": bad, "parameters": {"a0": {"value": 1}, "t_fixed": {"value": 1}}},
    )
    assert r.json()["error"]["code"] == "errors.formula_syntax"
    test = owner.post(
        "/api/formulas/test",
        json={
            "key": "time",
            "expressions": [
                {"name": "work", "level": "plant", "expr": "weight * gibtsnicht"},
                {"name": "duration", "level": "stop", "expr": "work"},
            ],
            "parameters": {},
        },
    ).json()
    codes = {p["code"] for p in test["problems"]}
    assert "unknown_name" in codes and "plant_var_outside_aggregate" in codes


def test_tier_switch_and_test_endpoint(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=30)
    tier2 = next(
        f for f in owner.get("/api/formulas", params={"key": "time"}).json()["formulas"] if f["tier"] == 2
    )
    active = next(v for v in tier2["versions"] if v["id"] == tier2["active_version_id"])
    t = owner.post(
        "/api/formulas/test",
        json={
            "key": "time",
            "expressions": active["expressions"],
            "parameters": active["parameters"],
            "order_id": oid,
        },
    ).json()
    assert t["ok"] and t["result"]["duration_min"] > 0
    owner.put("/api/settings", json={"scope": "tenant", "key": "time.formula_tier", "value": 2})
    est = owner.get(f"/api/orders/{oid}/estimate").json()
    assert est["formula"]["time"]["tier"] == 2
    assert est["duration_min"] == pytest.approx(t["result"]["duration_min"], abs=0.01)


def test_quote_pdf(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, weight=40, plants=3)
    q = owner.post(f"/api/orders/{oid}/quote", expect=201).json()
    assert q["number"].startswith("AN-") and q["gross_eur"] > 0
    assert sum(line["amount"] for line in q["lines"]) == pytest.approx(q["gross_eur"], abs=0.02)
    pdf = owner.get(q["url"]).content
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_weight_calibration(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, plants=0)
    for d in (40, 50, 60, 45):
        p = owner.post(
            f"/api/orders/{oid}/plants", expect=201, json={"pot_diameter_cm": d, "pot_height_cm": d}
        ).json()
        owner.patch(f"/api/plants/{p['id']}", json={"weight_measured_kg": round(p["weight_kg"] * 1.25, 1)})
    prop = owner.get("/api/weights/calibration").json()
    assert prop["n"] == 4 and prop["proposed"] == pytest.approx(1.25, abs=0.02)
    applied = owner.post("/api/weights/calibration/apply").json()
    assert applied["applied"]
    plants = owner.get("/api/plants", params={"order_id": oid}).json()
    assert all(abs(p["weight_kg"] - p["weight_measured_kg"]) < 1.5 for p in plants)

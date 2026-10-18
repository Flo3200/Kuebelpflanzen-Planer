"""Staged tour optimisation: fastest route first, then team composition variants, search experiments
and the final run in the same time budget; the report is stored with the plan."""

from __future__ import annotations

from tests.test_teams import MONDAY, _order


def _setup(owner, mode="auto", n_staff=4):
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.form_teams", "value": mode})
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 4})
    staff = [
        owner.post("/api/staff", expect=201, json={"name": f"Person {i}", "licences": ["B"]}).json()
        for i in range(n_staff)
    ]
    vans = [owner.post("/api/vehicles", expect=201, json={"name": f"Van {i}"}).json() for i in range(2)]
    for w in (12, 18, 25, 55):  # the last one needs three people
        _order(owner, w)
    return staff, vans


def _plan(owner):
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(MONDAY), "days": 3, "sync": True, "pack": False}
    ).json()
    plan = owner.get(f"/api/plans/{p['id']}").json()
    assert plan["status"] == "ready", plan.get("error")
    return plan


def test_staged_optimisation_report(new_tenant):
    _, owner = new_tenant()
    _setup(owner)
    plan = _plan(owner)
    st = plan["solver"]["stages"]
    assert st["strategy"] == "staged"
    # 1. fastest route over all stops as reference
    assert st["fastest"]["drive_min"] > 0 and st["fastest"]["distance_km"] > 0
    # 2. team variants: another than the rule only if clearly (3 %) better
    keys = [v["key"] for v in st["variants"]]
    assert keys[:2] == ["rule", "route_based"] and "size_2" in keys and "size_3" in keys
    route = next(v for v in st["variants"] if v["key"] == "route_based")
    assert any(3 in sizes for sizes in route["team_sizes"].values())  # the heavy trip gets three people
    rule = next(v for v in st["variants"] if v["key"] == "rule")
    chosen = next(v for v in st["variants"] if v["key"] == st["chosen"])
    assert st["chosen"] == "rule" or chosen["objective"] <= rule["objective"] * 0.97
    best = chosen["objective"]
    # 3. search experiments and 4. the final run
    assert len(st["search"]) == 2 and st["chosen_search"]
    assert st["final_time_limit_s"] == 4  # the final run keeps the full budget
    assert st["best_objective"] <= best
    assert plan["kpis"]["stops_planned"] == 4


def test_single_run_and_fixed_teams(new_tenant):
    _, owner = new_tenant()
    staff, vans = _setup(owner, mode="fixed")
    owner.post(
        "/api/teams",
        expect=201,
        json={"name": "Team A", "member_ids": [s["id"] for s in staff[:3]], "vehicle_id": vans[0]["id"]},
    )
    plan = _plan(owner)
    st = plan["solver"]["stages"]
    assert [v["key"] for v in st["variants"]] == ["rule"]  # fixed teams: no team variants
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.strategy", "value": "single"})
    assert _plan(owner)["solver"]["stages"] is None

"""Package D: fixed teams by the owner. With planning.form_teams = fixed a plan is always created;
stops that no team can take are listed with a reason and a hint which team or person would help."""

from __future__ import annotations

from datetime import date

from tests.test_phase3_estimates import make_order

MONDAY = date(2026, 10, 19)


def _setup(owner, n_staff: int = 3):
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.form_teams", "value": "fixed"})
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    staff = [
        owner.post("/api/staff", expect=201, json={"name": f"Person {i}", "licences": ["B"]}).json()
        for i in range(n_staff)
    ]
    van = owner.post("/api/vehicles", expect=201, json={"name": "Transporter"}).json()
    return staff, van


def _order(owner, weight: float) -> str:
    oid = make_order(owner, weight=weight, plants=1)
    owner.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
    return oid


def _plan(owner, days: int = 3) -> dict:
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(MONDAY), "days": days, "sync": True, "pack": False}
    ).json()
    plan = owner.get(f"/api/plans/{p['id']}").json()
    assert plan["status"] == "ready", plan.get("error")
    return plan


def test_fixed_mode_without_teams_still_plans(new_tenant):
    _, owner = new_tenant()
    _setup(owner)
    oid = _order(owner, 20)
    plan = _plan(owner)
    u = next(x for x in plan["unassigned"] if x["order_id"] == oid)
    assert u["reason"] == "no_units"
    assert [h["code"] for h in u["hints"]] == ["no_teams"]


def test_too_small_team_gets_a_hint_who_would_help(new_tenant):
    _, owner = new_tenant()
    staff, van = _setup(owner)
    owner.post(
        "/api/teams",
        expect=201,
        json={"name": "Team Nord", "member_ids": [staff[0]["id"], staff[1]["id"]], "vehicle_id": van["id"]},
    )
    light = _order(owner, 15)
    heavy = _order(owner, 55)  # needs three people
    plan = _plan(owner)
    planned = {s["order_id"] for t in plan["tours"] for s in t["stops"]}
    assert light in planned
    u = next(x for x in plan["unassigned"] if x["order_id"] == heavy)
    assert u["reason"] == "team_too_small" and u["need"] == 3
    hint = u["hints"][0]
    assert hint["code"] == "add_person"
    assert hint["params"]["team"] == "Team Nord" and hint["params"]["n"] == 1
    assert "Person 2" in hint["params"]["persons"]


def test_absent_member_and_weekdays_become_warnings(new_tenant):
    _, owner = new_tenant()
    staff, van = _setup(owner, n_staff=2)
    owner.post(
        "/api/teams",
        expect=201,
        json={
            "name": "Team Süd",
            "member_ids": [s["id"] for s in staff],
            "vehicle_id": van["id"],
            "weekdays": [0, 1],  # Monday and Tuesday
        },
    )
    owner.post(
        "/api/availability",
        expect=201,
        json={
            "resource_type": "staff",
            "resource_id": staff[0]["id"],
            "kind": "vacation",
            "date_from": str(MONDAY),
            "date_to": str(MONDAY),
        },
    )
    oid = _order(owner, 15)
    plan = _plan(owner)
    # Monday: member on vacation -> warning; Tuesday: the team works; Wednesday: not a team day
    tour_dates = {t["date"] for t in plan["tours"]}
    assert tour_dates == {"2026-10-20"}
    assert oid in {s["order_id"] for t in plan["tours"] for s in t["stops"]}
    issues = plan["solver"]["team_issues"]
    absent = next(i for i in issues if i["code"] == "team_member_absent")
    assert absent["params"]["team"] == "Team Süd" and absent["params"]["names"] == "Person 0"
    assert absent["params"]["days"] == "19.10."


def test_calendar_shows_team_conflicts(new_tenant):
    _, owner = new_tenant()
    staff, van = _setup(owner)
    a = owner.post(
        "/api/teams",
        expect=201,
        json={"name": "A", "member_ids": [staff[0]["id"], staff[1]["id"]], "vehicle_id": van["id"]},
    ).json()
    owner.post(
        "/api/teams",
        expect=201,
        json={"name": "B", "member_ids": [staff[1]["id"], staff[2]["id"]], "weekdays": [0]},
    )
    owner.post(
        "/api/availability",
        expect=201,
        json={
            "resource_type": "staff",
            "resource_id": staff[0]["id"],
            "kind": "sick",
            "date_from": "2026-10-20",
            "date_to": "2026-10-20",
        },
    )
    cal = owner.get("/api/availability-calendar", params={"start": str(MONDAY), "days": 3}).json()
    teams = {t["name"]: t for t in cal["teams"]}
    monday_a = {c["code"]: c for c in teams["A"]["days"]["2026-10-19"]["conflicts"]}
    assert monday_a["member_double"]["names"] == ["Person 1"]  # also in team B on Mondays
    tuesday_a = {c["code"]: c for c in teams["A"]["days"]["2026-10-20"]["conflicts"]}
    assert tuesday_a == {"member_absent": {"code": "member_absent", "names": ["Person 0"]}}
    assert teams["B"]["days"]["2026-10-20"]["valid"] is False
    assert teams["A"]["vehicle"] == "Transporter"
    # invalid days are refused
    owner.patch(f"/api/teams/{a['id']}", expect=400, json={"weekdays": [7]})

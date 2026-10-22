"""Round 2, package R: a tour can be ended early (switch, off by default); open stops go back to the
planning, the office gets a notification; the plan shows which stops could be postponed."""

from __future__ import annotations

from datetime import date, timedelta

from tests.test_phase3_estimates import make_order


def _plan_with_tour(owner):
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    for i in range(2):
        owner.post("/api/staff", expect=201, json={"name": f"Person {i}", "licences": ["B"]})
    owner.post("/api/vehicles", expect=201, json={"name": "Transporter"})
    for _ in range(3):
        oid = make_order(owner, weight=20, plants=1)
        owner.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
    day = date.today() + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    plan = owner.post(
        "/api/plans",
        expect=201,
        json={"start_date": day.isoformat(), "days": 1, "sync": True, "pack": False, "activate": True},
    ).json()
    return owner.get(f"/api/plans/{plan['id']}").json()


def test_abort_tour(new_tenant):
    _, owner = new_tenant()
    plan = _plan_with_tour(owner)
    tour = plan["tours"][0]
    assert "movable" not in tour["stops"][0]  # only with the switch on
    owner.post(f"/api/driver/tours/{tour['id']}/abort", expect=409, json={"reason": "late"})

    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.abort_enabled", "value": True})
    plan = owner.get(f"/api/plans/{plan['id']}").json()
    assert all(s["movable"] is True for x in plan["tours"] for s in x["stops"])
    # the first stop is already in progress
    first = tour["stops"][0]
    from datetime import UTC, datetime

    ev = {"client_id": "e1", "tour_id": tour["id"], "stop_id": first["id"], "kind": "arrive"}
    ev["at"] = datetime.now(UTC).isoformat()
    assert owner.post("/api/driver/events", json={"events": [ev]}).json()["ok"] == 1
    r = owner.post(
        f"/api/driver/tours/{tour['id']}/abort", json={"reason": "late", "note": "Stau auf der A8"}
    ).json()
    assert len(r["skipped"]) == len(tour["stops"]) - 1
    # (the plan view shows the order status; the stop status is in the driver's tour package)
    stops = {s["id"]: s["status"] for s in r["tour"]["stops"]}
    assert stops[first["id"]] == "arrived"
    assert sum(1 for v in stops.values() if v == "skipped") == len(tour["stops"]) - 1
    for x in r["skipped"]:
        assert owner.get(f"/api/orders/{x['order_id']}").json()["order"]["status"] == "confirmed"
    n = next(n for n in owner.get("/api/notifications").json()["items"] if n["kind"] == "tour_aborted")
    assert "Stau auf der A8" in n["body"] and "große Verspätung" in n["body"]
    owner.post(f"/api/driver/tours/{tour['id']}/abort", expect=400, json={"reason": "unknown"})

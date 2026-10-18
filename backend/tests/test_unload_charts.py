"""Package F: unloading time from the formula (changes with the plants, learnable from the driver
app), depot windows per tour, charts and the logistics dashboard with empty and with real data."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.db import RlsContext, session_scope
from app.models.field import UnloadMeasurement
from app.timemodel.unload import UnloadModel
from tests.test_teams import MONDAY, _order


def _plan(owner, days=2):
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(MONDAY), "days": days, "sync": True, "pack": False}
    ).json()
    owner.post(f"/api/plans/{p['id']}/activate")
    return owner.get(f"/api/plans/{p['id']}").json()


def _resources(owner, n_staff=2):
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    for i in range(n_staff):
        owner.post("/api/staff", expect=201, json={"name": f"Person {i}", "licences": ["B"]})
    owner.post("/api/vehicles", expect=201, json={"name": "Transporter"})


def test_unload_formula_grows_with_plants(new_tenant):
    tenant, owner = new_tenant()
    tid = uuid.UUID(tenant["id"])
    with session_scope(RlsContext(tenant_id=tid)) as db:
        um = UnloadModel(db, tid)
        few, many = um.minutes([20] * 3, 2), um.minutes([20] * 12, 2)
        # start formula: 8 + (1.5 · n + 0.02 · kg) / team
        assert few == pytest.approx(8 + (4.5 + 1.2) / 2, abs=0.1)
        assert many == pytest.approx(8 + (18 + 4.8) / 2, abs=0.1)
        assert um.minutes([20] * 12, 4) < many  # a bigger team unloads faster
    # the owner can switch to fixed minutes
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.unload_mode", "value": "fixed"})
    with session_scope(RlsContext(tenant_id=tid)) as db:
        assert UnloadModel(db, tid).minutes([20] * 12, 2) == 20.0
    # the formula is in the formula editor
    keys = {f["key"] for f in owner.get("/api/formulas").json()["formulas"]}
    assert "unload" in keys


def test_tours_get_unloading_windows_and_charts(new_tenant):
    _, owner = new_tenant()
    # empty tenant: charts and dashboard work without data
    empty = owner.get("/api/dashboard/charts", params={"start": str(MONDAY), "days": 7}).json()
    assert len(empty["utilisation"]) == 7 and empty["timeline"] == [] and empty["accuracy"] == []
    assert empty["unload"] == {"windows": [], "curve": [], "max_parallel": 0}
    dash = owner.get("/api/dashboard").json()["logistics"]
    assert dash["today"]["tours"] == [] and dash["unplanned"] == [] and dash["week"]["cost"] == 0
    _resources(owner)
    for w in (10, 15, 20):
        _order(owner, w)
    plan = _plan(owner)
    assert plan["tours"]
    for tour in plan["tours"]:
        assert tour["depot_start_min"] == tour["end_min"]
        assert tour["depot_end_min"] == round(tour["end_min"] + tour["unload_min"])
        assert tour["unload_min"] > 8  # fixed part of the formula plus the plants
    charts = owner.get(
        "/api/dashboard/charts", params={"start": str(MONDAY), "days": 3, "day": plan["tours"][0]["date"]}
    ).json()
    assert (
        charts["timeline"]
        and charts["timeline"][0]["depot_end_min"] > charts["timeline"][0]["depot_start_min"]
    )
    day = next(u for u in charts["utilisation"] if u["date"] == plan["tours"][0]["date"])
    assert day["staff_used"] >= 1 and day["vehicles_used"] == 1 and day["vehicles_pct"] == 100.0
    cost_day = next(c for c in charts["costs"] if c["date"] == plan["tours"][0]["date"])
    assert cost_day["cost"] > 0 and cost_day["cost_per_plant"] > 0
    assert charts["unload"]["max_parallel"] >= 1


def test_driver_unloading_events_become_measurements(new_tenant):
    tenant, owner = new_tenant()
    _resources(owner)
    _order(owner, 20)
    plan = _plan(owner, days=1)
    tour = plan["tours"][0]
    t0 = datetime.now(UTC) - timedelta(hours=1)

    def ev(kind, minutes):
        return {
            "client_id": uuid.uuid4().hex,
            "tour_id": tour["id"],
            "kind": kind,
            "at": (t0 + timedelta(minutes=minutes)).isoformat(),
        }

    r = owner.post(
        "/api/driver/events", json={"events": [ev("unload_start", 0), ev("unload_done", 17)]}
    ).json()
    assert r["ok"] == 2, r
    with session_scope(RlsContext(tenant_id=uuid.UUID(tenant["id"]))) as db:
        from sqlalchemy import select

        m = db.scalar(select(UnloadMeasurement).where(UnloadMeasurement.tour_id == uuid.UUID(tour["id"])))
        assert m is not None and m.minutes == pytest.approx(17) and m.n_plants == 1
        assert m.predicted_min == pytest.approx(tour["unload_min"])


def test_unload_formula_is_learned_from_measurements(new_tenant):
    tenant, owner = new_tenant()
    tid = uuid.UUID(tenant["id"])
    assert owner.get("/api/learning/unload").json()["proposed"] is None  # nothing measured yet
    rng = random.Random(5)
    true = {"u_fixed": 12.0, "u_plant": 2.0, "u_kg": 0.03}
    with session_scope(RlsContext(tenant_id=tid)) as db:
        for i in range(60):
            n, team = rng.randint(3, 20), rng.choice([2, 3])
            weights = [rng.uniform(10, 60) for _ in range(n)]
            minutes = true["u_fixed"] + (true["u_plant"] * n + true["u_kg"] * sum(weights)) / team
            db.add(
                UnloadMeasurement(
                    tenant_id=tid,
                    date=date(2026, 10, 1) + timedelta(days=i % 20),
                    source="synthetic",
                    team_size=team,
                    n_plants=n,
                    total_weight=sum(weights),
                    n_stops=3,
                    weights=weights,
                    minutes=minutes * rng.lognormvariate(0, 0.05),
                )
            )
    p = owner.get("/api/learning/unload").json()
    assert p["n"] == 60 and p["mae_after"] < p["mae_before"]
    assert p["proposed"]["u_fixed"] == pytest.approx(12, rel=0.25)
    assert p["proposed"]["u_plant"] == pytest.approx(2, rel=0.25)
    adopted = owner.post("/api/learning/unload/adopt").json()
    assert adopted["adopted_version"] >= 1  # first version of the tenant's own copy
    with session_scope(RlsContext(tenant_id=tid)) as db:
        um = UnloadModel(db, tid)
        assert um.formula.params["u_fixed"] == pytest.approx(p["proposed"]["u_fixed"])

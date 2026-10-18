"""Phase 4 acceptance: 100 demo orders are planned, all constraints hold, scenario "+1 person"
shows the difference in duration and cost. Plus manual moves, fixing/replanning, incompatible
plants, hard time windows and the performance test (500 stops, 10 teams)."""

from __future__ import annotations

import math
import os
import random
import time
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.db import RlsContext, session_scope, system_session
from app.models.core import Tenant
from app.models.masterdata import LICENCE_INCLUDES, StaffMember, Vehicle
from app.models.orders import Address, Customer, PickupOrder, Plant
from app.models.planning import Plan, Tour, TourStop
from app.timemodel.estimate import Estimator
from app.timemodel.plantfill import footprint_m2, volume_m3

START = date(2026, 10, 19)  # Monday


@pytest.fixture(scope="module")
def demo_tenant():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[0])
    spec["slug"] = f"plan-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Planer Test", f"planer-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Test", f"dispo-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(DemoOptions(seed=7, orders_per_tenant=100, tenants=[spec]), reset=False)
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1]


@pytest.fixture
def owner(demo_tenant, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(demo_tenant[1], DEMO_PASSWORD)
    # short solver runs in tests
    api.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 8})
    return api


def check_constraints(db, plan: Plan) -> dict:
    """Independent verification of a plan against the constraints."""
    tours = list(db.scalars(select(Tour).where(Tour.plan_id == plan.id)))
    est = Estimator(db, plan.tenant_id)
    staff_days: dict[tuple[str, date], str] = {}
    seen_orders: set = set()
    problems: list[str] = []
    staff = {
        str(s.id): s for s in db.scalars(select(StaffMember).where(StaffMember.tenant_id == plan.tenant_id))
    }
    vehicles = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.tenant_id == plan.tenant_id))}
    for t in tours:
        u = t.unit
        stops = list(db.scalars(select(TourStop).where(TourStop.tour_id == t.id).order_by(TourStop.position)))
        assert stops, "empty tour"
        # staff only once per day (several trips of the same unit are fine)
        for m in t.member_ids:
            key = (m, t.date)
            if key in staff_days and staff_days[key] != t.unit_key:
                problems.append(f"staff twice on {t.date}")
            staff_days[key] = t.unit_key
        # licence of the driver
        v = vehicles.get(t.vehicle_id)
        need = v.required_licence if v else "B"
        if t.trailer_id:
            need = {"B": "BE", "C1": "C1E", "C": "CE"}.get(need, "BE")
        drv = staff.get(str(t.driver_id))
        if drv is not None and not any(need in LICENCE_INCLUDES.get(lic, {lic}) for lic in drv.licences):
            problems.append(f"licence {need} missing")
        # working time window
        if t.start_min < u["start"] - 1 or t.end_min > u["hard_end"] + 1:
            problems.append(f"working time {t.start_min}-{t.end_min} outside {u['start']}-{u['hard_end']}")
        # capacity
        weight = area = volume = 0.0
        prev_end = t.start_min
        for s in stops:
            order = db.get(PickupOrder, s.order_id)
            assert s.order_id not in seen_orders, "order planned twice"
            seen_orders.add(s.order_id)
            plants = est.plants_of(order)
            paths = est.paths_for(order)
            members = u["members_detail"]
            calcs = [
                est.plant_calc(
                    p,
                    paths.get(p.access_path_id) or paths[None],
                    solo_limits=[m["solo_kg"] for m in members],
                    carry_factor=members[0]["carry_factor"],
                )
                for p in plants
            ]
            crew = max(c.crew.crew for c in calcs)
            if crew > len(t.member_ids):
                problems.append(f"team too small at {order.number}: {crew} > {len(t.member_ids)}")
            weight += sum(c.vars["weight"] for c in calcs)
            area += sum(
                footprint_m2(p, float(est.resolver.get("packing.crown_overlap", *est.plant_chain(p))))
                for p in plants
            )
            volume += sum(volume_m3(p) for p in plants)
            # dates
            if order.fixed_date and order.fixed_date != t.date:
                problems.append("fixed date violated")
            if order.earliest_date and order.latest_date and order.latest_date >= plan.start_date:
                if not (order.earliest_date <= t.date <= order.latest_date):
                    problems.append(f"date window violated for {order.number}")
            # time order
            if s.start_min < prev_end - 1 or s.start_min < s.arrival_min - 1:
                problems.append("time sequence")
            prev_end = s.end_min
        if weight > u["cap_weight"] + 1:
            problems.append(f"overweight {weight} > {u['cap_weight']}")
        if area > u["cap_area"] + 0.05:
            problems.append(f"over area {area} > {u['cap_area']}")
        if volume > u["cap_volume"] + 0.05:
            problems.append(f"over volume {volume} > {u['cap_volume']}")
    # breaks: a working day over 6 h has a break that does not overlap a visit
    by_unit: dict[str, list[Tour]] = {}
    for t in tours:
        by_unit.setdefault(t.unit_key, []).append(t)
    for key, ts in by_unit.items():
        span = max(t.end_min for t in ts) - min(t.start_min for t in ts)
        breaks = [b for t in ts for b in t.breaks]
        if span > 6 * 60 and ts[0].unit["break_min"] > 0 and not breaks:
            problems.append(f"missing break on {key}")
        for b in breaks:
            for t in ts:
                for s in db.scalars(select(TourStop).where(TourStop.tour_id == t.id)):
                    if s.start_min < b["end"] and b["start"] < s.end_min:
                        problems.append("break overlaps a visit")
    return {"problems": problems, "orders": len(seen_orders), "tours": len(tours)}


def test_plan_100_orders_all_constraints_hold(owner, demo_tenant):
    tid = demo_tenant[0]
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 10, "sync": True, "pack": False}
    ).json()
    plan = owner.get(f"/api/plans/{p['id']}").json()
    assert plan["status"] == "ready", plan.get("error")
    k = plan["kpis"]
    with session_scope(RlsContext(tenant_id=tid)) as db:
        n_orders = len(
            list(
                db.scalars(
                    select(PickupOrder).where(
                        PickupOrder.tenant_id == tid,
                        PickupOrder.direction == "pickup",
                        PickupOrder.status.in_(("confirmed", "planned")),
                    )
                )
            )
        )
        result = check_constraints(db, db.get(Plan, uuid.UUID(p["id"])))
    assert result["problems"] == [], result["problems"][:10]
    assert result["orders"] == k["stops_planned"]
    assert k["stops_planned"] + k["stops_unassigned"] == n_orders
    assert k["stops_planned"] >= 0.6 * n_orders
    assert all(u.get("reason") for u in plan["unassigned"])
    assert k["total_cost"] > 0 and k["days_until_done"] >= 1
    # orders of the active plan are marked as planned and show the coverage after planning
    any_planned = next(s for t in plan["tours"] for s in t["stops"])
    order = owner.get(f"/api/orders/{any_planned['order_id']}").json()["order"]
    assert order["status"] == "planned"
    assert order["estimate"]["plan_costs"]["self_cost"] > 0


def test_scenario_plus_one_person(owner):
    base = owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 6, "sync": True, "pack": False}
    ).json()
    owner.post(
        f"/api/plans/{base['id']}/scenarios",
        expect=201,
        json={"variants": [{"preset": "plus_person"}], "sync": True},
    )
    cmp = owner.get(f"/api/plans/{base['id']}/scenarios").json()
    variant = cmp["variants"][0]
    assert variant["status"] == "ready"
    d = variant["delta"]
    for key in ("days_until_done", "total_cost", "cost_per_plant", "stops_unassigned", "overtime_min"):
        assert key in d and d[key] is not None
    assert any(d[key] != 0 for key in ("days_until_done", "total_cost", "stops_unassigned"))
    # the extra person is actually used
    detail = owner.get(f"/api/plans/{variant['id']}").json()
    assert any(m.get("virtual") for t in detail["tours"] for m in t["members"])


def test_manual_move_recomputes(owner):
    p = owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 5, "sync": True, "pack": False}
    ).json()
    plan = owner.get(f"/api/plans/{p['id']}").json()
    tours = [t for t in plan["tours"] if t["stops"]]
    assert len(tours) >= 2
    src, dst = tours[0], tours[1]
    stop = src["stops"][0]
    after = owner.post(
        f"/api/tour-stops/{stop['id']}/move", json={"tour_id": dst["id"], "position": 1}
    ).json()
    moved_dst = next(t for t in after["tours"] if t["id"] == dst["id"])
    assert moved_dst["stops"][0]["id"] == stop["id"]
    assert moved_dst["changed_at"] is not None
    assert [s["position"] for s in moved_dst["stops"]] == list(range(1, len(moved_dst["stops"]) + 1))
    times = [s["start_min"] for s in moved_dst["stops"]]
    assert times == sorted(times)
    assert after["kpis"]["stops_planned"] == plan["kpis"]["stops_planned"]


def test_fix_cancel_and_replan(owner):
    p = owner.post(
        "/api/plans",
        expect=201,
        json={"start_date": str(START), "days": 6, "sync": True, "pack": False, "activate": True},
    ).json()
    owner.post(f"/api/plans/{p['id']}/activate")
    plan = owner.get(f"/api/plans/{p['id']}").json()
    fixed = plan["tours"][0]
    owner.patch(f"/api/tours/{fixed['id']}", json={"fixed": True})
    fixed_orders = {s["order_id"] for s in fixed["stops"]}
    # cancel an order of another tour -> removed from the plan, replanning suggested
    other = next(t for t in plan["tours"] if t["id"] != fixed["id"] and t["stops"])
    cancelled = other["stops"][0]["order_id"]
    owner.patch(f"/api/orders/{cancelled}", json={"status": "cancelled"})
    plan2 = owner.get(f"/api/plans/{p['id']}").json()
    assert any(r.startswith("cancelled:") for r in plan2["needs_replan"])
    assert cancelled not in {s["order_id"] for t in plan2["tours"] for s in t["stops"]}
    owner.post(f"/api/plans/{p['id']}/replan", json={"from_date": str(START), "sync": True})
    plan3 = owner.get(f"/api/plans/{p['id']}").json()
    assert plan3["status"] == "ready" and not plan3["needs_replan"]
    same_unit = [t for t in plan3["tours"] if t["unit_key"] == fixed["unit_key"]]
    assert same_unit and fixed_orders <= {s["order_id"] for t in same_unit for s in t["stops"]}
    assert cancelled not in {s["order_id"] for t in plan3["tours"] for s in t["stops"]}


# ------------------------------------------------------------------------------- synthetic tenants


def synthetic_tenant(n_orders: int, n_staff: int, n_vehicles: int, seed: int = 1, plants=(1, 3)) -> uuid.UUID:
    rng = random.Random(seed)
    from app.core.numbering import next_number
    from app.models.orders import AccessPath, PathSegment
    from app.settings.service import SettingsResolver
    from app.timemodel.plantfill import complete_plant

    with system_session() as db:
        t = Tenant(
            name=f"Synthetisch {seed}",
            slug=f"syn-{uuid.uuid4().hex[:8]}",
            depot_lat=48.78,
            depot_lon=9.18,
            status="active",
        )
        db.add(t)
        db.flush()
        tid = t.id
    with session_scope(RlsContext(tenant_id=tid)) as db:
        for i in range(n_staff):
            db.add(
                StaffMember(
                    tenant_id=tid,
                    name=f"Person {i:02d}",
                    licences=["B", "BE"],
                    qualifications=[],
                    active=True,
                )
            )
        for i in range(n_vehicles):
            db.add(
                Vehicle(
                    tenant_id=tid,
                    name=f"Transporter {i:02d}",
                    kind="van",
                    required_licence="B",
                    seats=3,
                    cargo_length_cm=400,
                    cargo_width_cm=175,
                    cargo_height_cm=190,
                    payload_kg=1200,
                    door_width_cm=155,
                    door_height_cm=180,
                )
            )
        db.flush()
        r = SettingsResolver(db, tid)
        for i in range(n_orders):
            c = Customer(tenant_id=tid, name=f"Kunde {i}")
            db.add(c)
            db.flush()
            ang, rad = rng.uniform(0, 2 * math.pi), 25 * math.sqrt(rng.random())
            a = Address(
                tenant_id=tid,
                customer_id=c.id,
                street=f"Weg {i}",
                postal_code="70000",
                city="Stuttgart",
                lat=48.78 + rad * math.cos(ang) / 111,
                lon=9.18 + rad * math.sin(ang) / 73,
            )
            db.add(a)
            db.flush()
            o = PickupOrder(
                tenant_id=tid,
                customer_id=c.id,
                address_id=a.id,
                season=2026,
                status="confirmed",
                direction="pickup",
                number=f"S-{next_number(db, tid, 'syn'):04d}",
                time_windows=[],
                priority=0,
                source="test",
            )
            db.add(o)
            db.flush()
            path = AccessPath(tenant_id=tid, order_id=o.id, name="Weg", confidence={})
            db.add(path)
            db.flush()
            db.add(
                PathSegment(
                    tenant_id=tid,
                    path_id=path.id,
                    position=0,
                    kind="flat",
                    length_m=rng.uniform(3, 25),
                    surface="paved",
                )
            )
            for _ in range(rng.randint(*plants)):
                pl = Plant(
                    tenant_id=tid,
                    order_id=o.id,
                    number=next_number(db, tid, "plant"),
                    access_path_id=path.id,
                    pot_diameter_cm=rng.uniform(25, 50),
                    pot_height_cm=rng.uniform(25, 45),
                    total_height_cm=rng.uniform(80, 170),
                    weight_kg=round(rng.uniform(8, 40), 1),
                    estimated_fields=[],
                    field_confidence={},
                    required_equipment=[],
                    incompatible_with=[],
                )
                db.add(pl)
                db.flush()
                complete_plant(db, pl, r)
    return tid


def plan_direct(tid: uuid.UUID, days: int, time_limit: float, **opts) -> Plan:
    from app.planning.planner import run_plan

    with session_scope(RlsContext(tenant_id=tid)) as db:
        plan = Plan(
            tenant_id=tid,
            name="Test",
            start_date=START,
            days=days,
            direction="pickup",
            options={"time_limit_s": time_limit, "pack": False, **opts},
            scenario={},
            kpis={},
            unassigned=[],
            units=[],
            solver={},
        )
        db.add(plan)
        db.flush()
        run_plan(db, plan)
        db.expunge(plan)
    return plan


def test_incompatible_plants_not_in_same_unit():
    tid = synthetic_tenant(6, 2, 1, seed=3, plants=(1, 1))
    with session_scope(RlsContext(tenant_id=tid)) as db:
        plants = list(db.scalars(select(Plant).where(Plant.tenant_id == tid).order_by(Plant.number)))
        a, b = plants[0], plants[1]
        a.incompatible_with = [str(b.id)]
        order_a, order_b = a.order_id, b.order_id
    plan = plan_direct(tid, days=3, time_limit=3)
    with session_scope(RlsContext(tenant_id=tid)) as db:
        units = {}
        for t in db.scalars(select(Tour).where(Tour.plan_id == plan.id)):
            for s in db.scalars(select(TourStop).where(TourStop.tour_id == t.id)):
                units[s.order_id] = t.unit_key
    assert order_a in units and order_b in units
    assert units[order_a] != units[order_b]


def test_hard_time_windows():
    tid = synthetic_tenant(8, 2, 1, seed=4, plants=(1, 1))
    with session_scope(RlsContext(tenant_id=tid)) as db:
        from app.core.context import system_actor
        from app.settings.service import set_value

        set_value(
            db, system_actor(tid), scope="tenant", key="planning.time_windows", value="hard", tenant_id=tid
        )
        orders = list(
            db.scalars(select(PickupOrder).where(PickupOrder.tenant_id == tid).order_by(PickupOrder.number))
        )
        for o in orders[:4]:
            o.time_windows = [{"from": "13:00", "to": "15:30"}]
        windowed = {o.id for o in orders[:4]}
    plan = plan_direct(tid, days=3, time_limit=3)
    with session_scope(RlsContext(tenant_id=tid)) as db:
        stops = list(
            db.scalars(
                select(TourStop).join(Tour, Tour.id == TourStop.tour_id).where(Tour.plan_id == plan.id)
            )
        )
        hit = [s for s in stops if s.order_id in windowed]
        assert hit, "windowed orders should be plannable"
        for s in hit:
            assert 13 * 60 <= s.start_min <= 15 * 60 + 30


@pytest.mark.skipif(os.environ.get("KP_SKIP_SLOW") == "1", reason="slow performance test")
def test_performance_500_stops_10_teams():
    tid = synthetic_tenant(500, 20, 10, seed=5, plants=(1, 2))
    limit = 60.0
    t0 = time.monotonic()
    plan = plan_direct(tid, days=10, time_limit=limit)
    elapsed = time.monotonic() - t0
    assert plan.status == "ready"
    assert plan.kpis["units"] >= 5
    # solver time stays within the configured limit (plus model building and result writing)
    assert plan.solver["seconds"] <= limit + 30, plan.solver
    assert elapsed <= limit * 1.5 + 60, elapsed
    assert plan.kpis["stops_planned"] >= 0.9 * 500, plan.kpis

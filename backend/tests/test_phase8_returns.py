"""Phase 8, part 1: spring return as its own planning mode.

Returns reuse plants and paths of the pickup, are created in bulk, respect the frost-safe date,
load at the depot before every trip, have their own time factor and price rule, are delivered
with a proof photo in the driver app and are packed with the first delivery at the door."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.db import RlsContext, session_scope
from app.models.field import Measurement
from app.models.masterdata import Species
from app.models.orders import PickupOrder, Plant
from app.models.planning import Tour, TourStop


@pytest.fixture(scope="module")
def demo():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[0])
    spec["slug"] = f"rueck-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Rück Test", f"rueck-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Rück", f"dispo-rueck-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(
        DemoOptions(seed=51, orders_per_tenant=48, tenants=[spec], measurements=False), reset=False
    )
    t = report["tenants"][0]
    return uuid.UUID(t["id"]), spec["owner"][1], spec["slug"], t


@pytest.fixture
def owner(demo, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(demo[1], DEMO_PASSWORD)
    api.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 4})
    return api


def _returns(tid):
    with session_scope(RlsContext(tenant_id=tid)) as db:
        rows = list(
            db.scalars(
                select(PickupOrder).where(PickupOrder.tenant_id == tid, PickupOrder.direction == "return")
            )
        )
        db.expunge_all()
        return rows


def _is_sensitive(db, p: Plant) -> bool:
    sp = db.get(Species, p.species_id) if p.species_id else None
    return bool(
        p.frost_sensitive
        or (p.frost_sensitive is None and sp is not None and sp.frost_sensitivity == "tender")
    )


def test_demo_has_stored_pickups_and_returns(demo):
    tid = demo[0]
    rets = _returns(tid)
    assert rets and demo[3].get("returns") == len(rets)
    with session_scope(RlsContext(tenant_id=tid)) as db:
        for r in rets:
            pickup = db.get(PickupOrder, r.return_of_id)
            assert pickup.status == "stored" and r.status == "confirmed" and r.number.startswith("R-")
            assert r.earliest_date and r.latest_date and r.earliest_date.month in (4, 5)
            plants = list(db.scalars(select(Plant).where(Plant.order_id == pickup.id)))
            assert all(p.storage_area_id for p in plants)
            assert (r.estimate or {}).get("duration_min")


def test_bulk_creation_is_idempotent(owner, demo):
    tid = demo[0]
    with session_scope(RlsContext(tenant_id=tid)) as db:
        extra = db.scalar(
            select(PickupOrder)
            .where(
                PickupOrder.tenant_id == tid,
                PickupOrder.direction == "pickup",
                PickupOrder.status == "confirmed",
            )
            .order_by(PickupOrder.number.desc())
        )
        extra.status = "picked_up"
        extra_id = extra.id
    before = len(_returns(tid))
    year = date.today().year + 1
    r = owner.post(
        "/api/orders/returns", json={"earliest_date": f"{year}-04-01", "latest_date": f"{year}-05-31"}
    ).json()
    assert r["created"] == 1 and r["existing"] == before
    again = owner.post("/api/orders/returns", json={"earliest_date": f"{year}-04-01"}).json()
    assert again["created"] == 0
    ret = next(x for x in _returns(tid) if x.return_of_id == extra_id)
    assert ret.earliest_date == date(year, 4, 1) and ret.latest_date == date(year, 5, 31)
    # the order list can be filtered by direction
    rows = owner.get("/api/orders", params={"direction": "return"}).json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert items and all(x["number"].startswith("R-") for x in items)


def _monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


@pytest.fixture(scope="module")
def april_plan(demo, make_client_module):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client_module()
    api.login(demo[1], DEMO_PASSWORD)
    api.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 4})
    year = date.today().year + 1
    start = _monday(date(year, 4, 21))
    p = api.post(
        "/api/plans",
        expect=201,
        json={"start_date": str(start), "days": 10, "direction": "return", "sync": True, "pack": False},
    ).json()
    plan = api.get(f"/api/plans/{p['id']}").json()
    assert plan["status"] == "ready", plan.get("error")
    return api, plan


@pytest.fixture(scope="module")
def make_client_module(app):
    from fastapi.testclient import TestClient

    from tests.conftest import Api

    clients = []

    def _make():
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return Api(c)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_return_plan_frost_rule_and_loading_before_departure(demo, april_plan):
    tid = demo[0]
    api, plan = april_plan
    assert plan["direction"] == "return" and plan["tours"]
    frost_safe = date(date.today().year + 1, 5, 15)
    with session_scope(RlsContext(tenant_id=tid)) as db:
        planned_orders = 0
        for t in plan["tours"]:
            assert t["stops"]
            for s in t["stops"]:
                order = db.get(PickupOrder, uuid.UUID(s["order_id"]))
                assert order.direction == "return"
                planned_orders += 1
                plants = list(db.scalars(select(Plant).where(Plant.order_id == order.return_of_id)))
                if any(_is_sensitive(db, p) for p in plants):
                    assert date.fromisoformat(t["date"]) >= frost_safe, s["number"]
        assert planned_orders
        # frost-sensitive returns before the frost-safe date are explained
        reasons = {u["reason"] for u in plan["unassigned"]}
        has_sensitive = False
        for r in _returns(tid):
            plants = list(db.scalars(select(Plant).where(Plant.order_id == r.return_of_id)))
            has_sensitive |= any(_is_sensitive(db, p) for p in plants)
        if has_sensitive and date.fromisoformat(plan["tours"][-1]["date"]) < frost_safe:
            assert "frost" in reasons
        # loading at the depot happens before the first stop of every trip
        load_min = 25
        for t in plan["tours"]:
            first = t["stops"][0]
            assert first["arrival_min"] >= t["start_min"] + load_min, (
                t["label"],
                t["start_min"],
                first["arrival_min"],
            )


def test_return_load_plan_first_delivery_at_the_door(april_plan):
    api, plan = april_plan
    tour = next((t for t in plan["tours"] if len(t["stops"]) >= 2), None)
    if tour is None:
        pytest.skip("no tour with two stops")
    lp = api.post(f"/api/tours/{tour['id']}/load-plan").json()
    assert lp["tour"]["direction"] == "return"
    placements = lp["plan"]["placements"]
    by_stop: dict[int, list[float]] = {}
    for p in placements:
        by_stop.setdefault(p["stop_position"], []).append(p["x"])
    first, last = min(by_stop), max(by_stop)
    if first != last and lp["tour"]["load_status"] == "ok":
        assert max(by_stop[first]) >= min(by_stop[last])
        # loading sequence at the depot: last delivery first
        seq = [p["stop_position"] for p in sorted(placements, key=lambda p: p["sequence"])]
        assert seq == sorted(seq, reverse=True)


def test_return_time_factor_and_price_rules(owner, demo):
    tid = demo[0]
    ret = _returns(tid)[0]
    base = owner.get(f"/api/orders/{ret.id}").json()["order"]["estimate"]
    owner.put("/api/settings", json={"scope": "tenant", "key": "returns.time_factor", "value": 1.5})
    try:
        est = owner.get(f"/api/orders/{ret.id}").json()["order"]["estimate"]
        assert est["duration_min"] == pytest.approx(base["duration_min"] * 1.5, rel=0.02)
    finally:
        owner.put("/api/settings", json={"scope": "tenant", "key": "returns.time_factor", "value": 1.0})
    owner.put("/api/settings", json={"scope": "tenant", "key": "returns.price_mode", "value": "included"})
    try:
        est = owner.get(f"/api/orders/{ret.id}").json()["order"]["estimate"]
        assert est["price"]["gross"] == 0
        pickup = owner.get(f"/api/orders/{ret.return_of_id}").json()["order"]["estimate"]
        assert pickup["price"]["gross"] > 0  # the pickup keeps its price
    finally:
        owner.put("/api/settings", json={"scope": "tenant", "key": "returns.price_mode", "value": "separate"})


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


def test_driver_delivers_with_proof_photo(demo, april_plan, make_client):
    tid = demo[0]
    api, plan = april_plan
    api.post(f"/api/plans/{plan['id']}/activate")
    tour = plan["tours"][0]
    stop = tour["stops"][0]
    staff_id = tour["members"][0]["id"]
    with session_scope(RlsContext(tenant_id=tid)) as db:
        from app.models.core import User

        user = db.scalar(
            select(User).where(User.tenant_id == tid, User.staff_member_id == uuid.UUID(staff_id))
        )
        user_id = str(user.id) if user else None
    if user_id is None:
        user_id = api.post(
            "/api/users",
            expect=201,
            json={"name": "Fahrer Rück", "role": "driver", "staff_member_id": staff_id},
        ).json()["id"]
    pin = f"{uuid.uuid4().int % 900000 + 100000}"
    api.post(f"/api/users/{user_id}/pin", json={"pin": pin})
    drv = make_client()
    drv.post("/api/auth/driver/pin", json={"tenant": demo[2], "pin": pin})
    day = drv.get("/api/driver/day", params={"on": tour["date"]}).json()
    t = next(x for x in day["tours"] if x["id"] == tour["id"])
    st = next(x for x in t["stops"] if x["id"] == stop["id"])
    assert st["order"]["direction"] == "return"
    assert all(p.get("storage") for p in st["plants"])  # where to find the plants when loading
    t0 = datetime.now(UTC) - timedelta(hours=2)

    def ev(kind, minutes, **kw):
        return {
            "client_id": uuid.uuid4().hex,
            "tour_id": tour["id"],
            "stop_id": stop["id"],
            "kind": kind,
            "at": (t0 + timedelta(minutes=minutes)).isoformat(),
            **kw,
        }

    res = drv.post("/api/driver/events", json={"events": [ev("arrive", 30), ev("carry_start", 33)]}).json()
    assert res["ok"] == 2
    delivered = ev("delivered", 50, photo_client_id=uuid.uuid4().hex)
    assert (
        drv.post("/api/driver/events", json={"events": [delivered]}).json()["results"][0]["error"]
        == "errors.event_photo_required"
    )
    drv.post(
        "/api/driver/photos",
        expect=201,
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data={"client_id": delivered["photo_client_id"], "stop_id": stop["id"], "kind": "delivery_proof"},
    )
    assert drv.post("/api/driver/events", json={"events": [delivered, ev("leave", 52)]}).json()["ok"] == 2
    with session_scope(RlsContext(tenant_id=tid)) as db:
        ret = db.get(PickupOrder, uuid.UUID(stop["order_id"]))
        assert ret.status == "returned"
        assert db.get(PickupOrder, ret.return_of_id).status == "returned"
        assert db.get(TourStop, uuid.UUID(stop["id"])).status == "done"
        m = db.scalar(select(Measurement).where(Measurement.stop_id == uuid.UUID(stop["id"])))
        assert m is not None and m.duration_min == pytest.approx(20, abs=0.01)
        assert db.get(Tour, uuid.UUID(tour["id"])).status == "in_progress"

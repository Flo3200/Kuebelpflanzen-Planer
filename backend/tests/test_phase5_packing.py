"""Phase 5 acceptance: every planned tour has a valid load plan or a clear reason why not.

Packer unit tests use an independent geometry check (not the packer's own functions):
pots never overlap, everything inside the cargo space, below the roof, below the payload,
pots never on wheel arches, shelves within clearance and load. Plus loading order, lying
plants, German reasons and the load-plan API.
"""

from __future__ import annotations

import math
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.db import RlsContext, session_scope
from app.models.planning import Plan, Tour
from app.packing.geometry import Box, PlantItem, Shelf, Space
from app.packing.packer import Packer, PackSettings
from app.packing.service import result_payload

START = date(2026, 10, 19)


def van(**kw) -> Space:
    base = dict(
        id="van",
        name="Transporter",
        kind="van",
        length=330,
        width=178,
        height=190,
        door_w=160,
        door_h=180,
        payload=1100,
        front_axle_x=-80,
        rear_axle_x=250,
        max_front_extra=600,
        max_rear_extra=900,
        obstacles=[Box(245, 0, 340, 20, 32), Box(245, 158, 340, 178, 32)],
    )
    base.update(kw)
    return Space(**base)


def plant(
    n: int,
    stop: int = 1,
    pot: float = 35,
    height: float = 120,
    crown: float = 60,
    weight: float = 20,
    tilt: bool = True,
    shape: str = "round",
    **kw,
) -> PlantItem:
    pot_h = pot * 0.85
    base = dict(
        plant_id=f"p{n}",
        number=n,
        order_id=f"o{stop}",
        stop_position=stop,
        label=f"#{n} Testpflanze",
        weight=weight,
        pot_shape=shape,
        pot_d=pot,
        pot_l=pot,
        pot_w=pot,
        pot_h=pot_h,
        crown_shape="sphere",
        crown_w=crown,
        crown_h=max(10.0, height - pot_h - 10),
        crown_start=10,
        total_h=height,
        overlap=0.15,
        compress=0.3,
        can_tilt=tilt,
        tilt_max_deg=90,
        sensitive=False,
        must_secure=False,
        tip_tendency=0.3,
    )
    base.update(kw)
    return PlantItem(**base)


def settings(**kw) -> PackSettings:
    s = PackSettings(
        clearance=2,
        heavy_kg=40,
        cog_tolerance=0.15,
        tall_ratio=3,
        time_limit_s=1.0,
        sort_rule="tour_then_size",
        direction="pickup",
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------- independent validation


def _rigid_shape(p: dict) -> tuple[str, tuple[float, ...]]:
    d = p["dims"]
    if p["orientation"] == "upright":
        if d["pot_shape"] == "round":
            return "circle", (p["x"], p["y"], d["pot_d"] / 2)
        return "rect", (
            p["x"] - d["pot_l"] / 2,
            p["y"] - d["pot_w"] / 2,
            p["x"] + d["pot_l"] / 2,
            p["y"] + d["pot_w"] / 2,
        )
    lx, ly, _h = d["box"]
    return "rect", (p["x"] - lx / 2, p["y"] - ly / 2, p["x"] + lx / 2, p["y"] + ly / 2)


def _overlap(a, b, tol: float = 0.6) -> bool:
    (ka, va), (kb, vb) = a, b
    if ka == "circle" and kb == "circle":
        return math.hypot(va[0] - vb[0], va[1] - vb[1]) < va[2] + vb[2] - tol
    ra = va if ka == "rect" else (va[0] - va[2], va[1] - va[2], va[0] + va[2], va[1] + va[2])
    rb = vb if kb == "rect" else (vb[0] - vb[2], vb[1] - vb[2], vb[0] + vb[2], vb[1] + vb[2])
    return ra[0] < rb[2] - tol and rb[0] < ra[2] - tol and ra[1] < rb[3] - tol and rb[1] < ra[3] - tol


def _bbox(shape) -> tuple[float, float, float, float]:
    k, v = shape
    return v if k == "rect" else (v[0] - v[2], v[1] - v[2], v[0] + v[2], v[1] + v[2])


def validate(payload: dict) -> list[str]:
    """Independent check of a load plan payload (as stored and sent to the UI)."""
    problems = []
    spaces = {s["id"]: s for s in payload["spaces"]}
    weight: dict[str, float] = {}
    shelf_load: dict[str, float] = {}
    by_level: dict[tuple[str, str], list[tuple[dict, tuple]]] = {}
    for p in payload["placements"]:
        sp = spaces[p["space_id"]]
        shape = _rigid_shape(p)
        x0, y0, x1, y1 = _bbox(shape)
        if x0 < -0.6 or y0 < -0.6 or x1 > sp["length"] + 0.6 or y1 > sp["width"] + 0.6:
            problems.append(f"#{p['number']} outside the cargo space")
        top = p["z"] + p["dims"]["box"][2]
        if top > sp["height"] + 0.1:
            problems.append(f"#{p['number']} higher than the roof")
        weight[sp["id"]] = weight.get(sp["id"], 0) + p["dims"]["weight"]
        if p["level"] == "floor":
            for ob in sp["obstacles"]:
                # the pot itself never stands on an obstacle (lying: pot at the front end)
                if p["orientation"] == "upright":
                    px0, py0, px1, py1 = x0, y0, x1, y1
                else:
                    r = p["dims"]["pot_d"] / 2
                    if p["orientation"] == "lying_y":
                        px0, py0, px1, py1 = p["x"] - r, y0, p["x"] + r, y0 + p["dims"]["pot_h"]
                    else:
                        px0, py0, px1, py1 = x0, p["y"] - r, x0 + p["dims"]["pot_h"], p["y"] + r
                if (
                    px0 < ob["x1"] - 0.6
                    and ob["x0"] < px1 - 0.6
                    and py0 < ob["y1"] - 0.6
                    and ob["y0"] < py1 - 0.6
                ):
                    problems.append(f"#{p['number']} pot on an obstacle")
        else:
            sh = next(s for s in sp["shelves"] if s["id"] == p["level"])
            shelf_load[sh["id"]] = shelf_load.get(sh["id"], 0) + p["dims"]["weight"]
            if p["dims"]["total_h"] > sh["clearance"] + 0.1:
                problems.append(f"#{p['number']} too tall for the shelf")
        by_level.setdefault((p["space_id"], p["level"]), []).append((p, shape))
    for items in by_level.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _overlap(items[i][1], items[j][1]):
                    problems.append(f"pots #{items[i][0]['number']} and #{items[j][0]['number']} overlap")
    for sid, w in weight.items():
        if w > spaces[sid]["payload"] + 0.01:
            problems.append(f"payload of {sid} exceeded")
    for s in payload["spaces"]:
        for sh in s["shelves"]:
            if shelf_load.get(sh["id"], 0) > sh["max_load"] + 0.01:
                problems.append(f"shelf {sh['name']} overloaded")
    return problems


def pack(items, spaces=None, **kw):
    spaces = spaces or [van()]
    res = Packer(spaces, settings(**kw)).run(items)
    return res, result_payload(res, spaces)


# ---------------------------------------------------------------- packer unit tests


def test_simple_load_is_valid_and_complete():
    items = [
        plant(i, stop=1 + i // 3, pot=30 + 3 * (i % 4), height=90 + 10 * (i % 5), crown=50 + 5 * (i % 3))
        for i in range(9)
    ]
    res, payload = pack(items)
    assert res.ok, res.message
    assert len(payload["placements"]) == 9
    assert validate(payload) == []
    assert all(p["instruction"] for p in payload["placements"])
    assert res.message == "Ladeplan in Ordnung"


def test_square_pots_and_heavy_plants():
    items = [plant(i, pot=45, shape="square", weight=60, height=110, crown=70) for i in range(6)]
    res, payload = pack(items)
    assert res.ok, res.message
    assert validate(payload) == []
    # heavy plants get a strap or stand low; the instruction mentions the position
    assert all("auf den Boden" in p["instruction"] for p in payload["placements"])


def _blocked(payload: dict, unload_first) -> list[str]:
    """Plants that are blocked on their way to the door by a plant unloaded later in the same lane."""
    out = []
    pl = payload["placements"]
    for p in pl:
        px0, py0, px1, py1 = _bbox(_rigid_shape(p))
        for q in pl:
            if q is p or q["space_id"] != p["space_id"] or not unload_first(p, q):
                continue
            qx0, qy0, qx1, qy1 = _bbox(_rigid_shape(q))
            if py0 < qy1 - 0.6 and qy0 < py1 - 0.6 and qx0 >= px1 - 0.6:
                out.append(f"#{p['number']} behind #{q['number']}")
    return out


def test_pickup_loading_order_never_blocks():
    items = [plant(10 * s + k, stop=s, pot=30, height=100, crown=45) for s in (1, 2, 3) for k in range(3)]
    res, payload = pack(items)
    assert res.ok, res.message
    # loading sequence follows the stops; a plant loaded later never ends up deeper in the same lane
    seq = [p["stop_position"] for p in sorted(payload["placements"], key=lambda p: p["sequence"])]
    assert seq == sorted(seq)
    assert _blocked(payload, lambda p, q: q["stop_position"] < p["stop_position"]) == []
    first = [p["x"] for p in payload["placements"] if p["stop_position"] == 1]
    last = [p["x"] for p in payload["placements"] if p["stop_position"] == 3]
    assert min(first) < max(last)


def test_return_unloading_order_never_blocks():
    items = [plant(10 * s + k, stop=s, pot=30, height=100, crown=45) for s in (1, 2, 3) for k in range(2)]
    res, payload = pack(items, direction="return")
    assert res.ok, res.message
    # the plants delivered first must not be behind plants delivered later (same lane)
    assert _blocked(payload, lambda p, q: p["stop_position"] < q["stop_position"]) == []
    seq = [p["stop_position"] for p in sorted(payload["placements"], key=lambda p: p["sequence"])]
    assert seq == sorted(seq, reverse=True)


def test_tall_tiltable_plant_lies_down():
    items = [
        plant(1, pot=35, height=260, crown=60, tilt=True),
        plant(2, pot=30, height=100, crown=40, stop=2),
    ]
    res, payload = pack(items)
    assert res.ok, res.message
    tall = next(p for p in payload["placements"] if p["number"] == 1)
    assert tall["orientation"] == "lying_x"
    assert "liegend" in tall["instruction"]
    assert validate(payload) == []


def test_lane_for_lying_plant_of_a_later_stop_stays_free():
    """Plants loaded before a lying plant must not block its way from the door to its place."""
    items = [
        plant(1, stop=1, pot=35, height=110, crown=60),
        plant(2, stop=1, pot=32, height=120, crown=55),
        plant(3, stop=2, pot=30, height=250, crown=50, tilt=True),
    ]
    res, payload = pack(items)
    assert res.ok, res.message
    lying = next(p for p in payload["placements"] if p["orientation"] == "lying_x")
    ly0, ly1 = lying["y"] - lying["dims"]["box"][1] / 2, lying["y"] + lying["dims"]["box"][1] / 2
    for p in payload["placements"]:
        if p["sequence"] < lying["sequence"]:
            x0, y0, x1, y1 = _bbox(_rigid_shape(p))
            assert y1 <= ly0 + 0.6 or y0 >= ly1 - 0.6, f"#{p['number']} blocks the lane"


def test_too_tall_and_not_tiltable_has_german_reason():
    items = [plant(1, height=240, tilt=False), plant(2)]
    res, payload = pack(items)
    assert not res.ok
    assert [u["reason"] for u in res.unplaced] == ["height"]
    assert "#1 Testpflanze" in res.message and "zu hoch" in res.message
    assert validate(payload) == []  # the rest is still a valid partial plan


def test_pot_wider_than_door():
    res, _payload = pack([plant(1, pot=170, crown=170, height=120)])
    assert not res.ok and res.unplaced[0]["reason"] == "door_width"
    assert "breiter als Tür" in res.message


def test_payload_limit():
    items = [plant(i, weight=300, pot=40, height=100) for i in range(5)]
    res, payload = pack(items)
    assert not res.ok
    assert any(u["reason"] == "payload" for u in res.unplaced)
    assert "Nutzlast" in res.message
    assert validate(payload) == []


def test_pots_never_on_wheel_arches():
    items = [plant(i, pot=40, height=100, crown=50, stop=1 + i // 4) for i in range(14)]
    _res, payload = pack(items)
    assert validate(payload) == []


def test_shelf_used_within_clearance_and_load():
    shelf = Shelf("s1", "Regal links", 0, 0, 160, 45, 95, clearance=80, max_load=40, blocks_floor=True)
    items = [plant(i, pot=22, height=60, crown=30, weight=12) for i in range(5)]
    items += [plant(10 + i, pot=38, height=150, crown=60, weight=25, stop=2) for i in range(3)]
    res, payload = pack(items, spaces=[van(shelves=[shelf])])
    assert res.ok, res.message
    assert validate(payload) == []
    on_shelf = [p for p in payload["placements"] if p["level"] == "s1"]
    assert on_shelf and sum(p["dims"]["weight"] for p in on_shelf) <= 40
    # nothing tall stands below a shelf that blocks the floor
    for p in payload["placements"]:
        if p["level"] == "floor" and p["x"] < 160 and p["y"] < 45:
            assert p["z"] + p["dims"]["box"][2] <= 95


def test_trailer_tongue_load_is_checked():
    trailer = Space(
        id="tr",
        name="Anhänger",
        kind="trailer",
        length=300,
        width=150,
        height=180,
        door_w=150,
        door_h=180,
        payload=750,
        hitch_x=-150,
        rear_axle_x=170,
        max_tongue=50,
        min_tongue=10,
    )
    items = [plant(i, weight=70, pot=40, height=100, crown=45) for i in range(4)]
    res, _payload = pack(items, spaces=[trailer])
    m = res.metrics["spaces"]["tr"]
    assert "tongue_load" in m
    if res.ok:
        assert 10 <= m["tongue_load"] <= 50
    else:
        assert "Stützlast" in res.message


def test_vehicle_plus_trailer():
    trailer = Space(
        id="tr",
        name="Anhänger",
        kind="trailer",
        length=250,
        width=150,
        height=180,
        door_w=150,
        door_h=180,
        payload=750,
        hitch_x=-120,
        rear_axle_x=140,
        max_tongue=100,
        min_tongue=0,
    )
    items = [plant(i, pot=45, height=120, crown=70, stop=1 + i // 5) for i in range(20)]
    res, payload = pack(items, spaces=[van(), trailer])
    assert validate(payload) == []
    assert {p["space_id"] for p in payload["placements"]} == {"van", "tr"} or res.ok


def test_deterministic():
    items = [
        plant(i, stop=1 + i // 4, pot=28 + i % 7 * 3, height=80 + i % 6 * 25, crown=40 + i % 5 * 10)
        for i in range(16)
    ]
    a, pa = pack(items)
    b, pb = pack(items)
    assert [(p["number"], p["x"], p["y"]) for p in pa["placements"]] == [
        (p["number"], p["x"], p["y"]) for p in pb["placements"]
    ]
    assert a.ok == b.ok


# ---------------------------------------------------------------- plan level acceptance


@pytest.fixture(scope="module")
def pack_tenant():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[0])
    spec["slug"] = f"pack-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Lade Test", f"lade-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Lade", f"dispo-lade-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(DemoOptions(seed=11, orders_per_tenant=35, tenants=[spec]), reset=False)
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1]


@pytest.fixture
def pack_owner(pack_tenant, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(pack_tenant[1], DEMO_PASSWORD)
    for key, value in (
        ("planning.time_limit_s", 4),
        ("packing.time_limit_s", 1),
        ("planning.pack_retry_limit", 2),
    ):
        api.put("/api/settings", json={"scope": "tenant", "key": key, "value": value})
    return api


def _plants_per_tour(tid: uuid.UUID, plan_id: str) -> dict[str, int]:
    from app.models.orders import PickupOrder, Plant
    from app.models.planning import TourStop

    out = {}
    with session_scope(RlsContext(tenant_id=tid)) as db:
        for t in db.scalars(select(Tour).where(Tour.plan_id == uuid.UUID(plan_id))):
            n = 0
            for st in db.scalars(select(TourStop).where(TourStop.tour_id == t.id)):
                order = db.get(PickupOrder, st.order_id)
                source = order.return_of_id or order.id
                n += len(
                    list(
                        db.scalars(
                            select(Plant.id).where(Plant.order_id == source, Plant.deleted_at.is_(None))
                        )
                    )
                )
            out[str(t.id)] = n
    return out


def test_every_tour_has_valid_load_plan_or_reason(pack_owner, pack_tenant):
    p = pack_owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 5, "sync": True, "pack": True}
    ).json()
    plan = pack_owner.get(f"/api/plans/{p['id']}").json()
    assert plan["status"] == "ready", plan.get("error")
    assert plan["tours"]
    plants = _plants_per_tour(pack_tenant[0], p["id"])
    ok = 0
    for t in plan["tours"]:
        lp = pack_owner.get(f"/api/tours/{t['id']}/load-plan").json()
        status, payload = lp["tour"]["load_status"], lp["plan"]
        assert status in ("ok", "failed"), lp["tour"]
        assert payload is not None
        assert validate(payload) == [], (t["label"], validate(payload)[:5])
        # every plant of the tour is either placed or listed with a reason
        assert len(payload["placements"]) + len(payload["unplaced"]) == plants[t["id"]]
        if status == "ok":
            ok += 1
            assert not payload["unplaced"]
        else:
            msg = lp["tour"]["load_message"] or ""
            assert ("passen nicht" in msg) or ("last" in msg), msg
            assert payload["unplaced"] or payload["violations"]
            assert all(u["reason"] for u in payload["unplaced"])
    assert ok >= 0.7 * len(plan["tours"])
    with session_scope(RlsContext(tenant_id=pack_tenant[0])) as db:
        stored = db.get(Plan, uuid.UUID(p["id"]))
        assert "attempts" in stored.solver


def test_recompute_single_tour_load_plan(pack_owner, pack_tenant):
    p = pack_owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 3, "sync": True, "pack": False}
    ).json()
    plan = pack_owner.get(f"/api/plans/{p['id']}").json()
    tour = plan["tours"][0]
    before = pack_owner.get(f"/api/tours/{tour['id']}/load-plan").json()
    assert before["tour"]["load_status"] == "unknown"
    after = pack_owner.post(f"/api/tours/{tour['id']}/load-plan").json()
    assert after["tour"]["load_status"] in ("ok", "failed")
    assert validate(after["plan"]) == []
    # all tours of a plan at once (job)
    res = pack_owner.post(f"/api/plans/{p['id']}/load-plans?sync=true").json()
    assert res["status"] == "done" and res["result"]["tours"] == len(plan["tours"])
    with session_scope(RlsContext(tenant_id=pack_tenant[0])) as db:
        statuses = [t.load_status for t in db.scalars(select(Tour).where(Tour.plan_id == uuid.UUID(p["id"])))]
    assert all(s in ("ok", "failed") for s in statuses)


def test_load_plan_not_visible_to_other_tenant(pack_owner, new_tenant):
    p = pack_owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 2, "sync": True, "pack": False}
    ).json()
    tour = pack_owner.get(f"/api/plans/{p['id']}").json()["tours"][0]
    _tenant, other = new_tenant()
    other.get(f"/api/tours/{tour['id']}/load-plan", expect=404)
    other.post(f"/api/tours/{tour['id']}/load-plan", expect=404)

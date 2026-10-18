"""Package G: AI proposal for the load arrangement as start solution. The packer checks every rule and
improves it; packing.mode rules / ai_start / compare."""

from __future__ import annotations

from app.packing.ai_layout import fake_layout, request_context
from app.packing.packer import Packer, StartLayout
from app.packing.service import result_payload
from tests.test_phase5_packing import (  # noqa: F401 - fixtures
    START,
    _blocked,
    pack_owner,  # noqa: F811
    pack_tenant,  # noqa: F811
    plant,
    settings,
    validate,
    van,
)


def _items():
    return [
        plant(10 * s + k, stop=s, pot=30 + 4 * k, height=90 + 15 * k, crown=45 + 5 * k)
        for s in (1, 2)
        for k in range(3)
    ]


def test_ai_start_layout_is_checked_and_valid():
    items, spaces = _items(), [van()]
    proposal = fake_layout(request_context(spaces, items, "pickup"))
    from app.packing.ai_layout import parse_layout

    layout = parse_layout(proposal, items, spaces)
    assert len(layout.positions) == len(items)
    res = Packer(spaces, settings()).run(items, layout)
    payload = result_payload(res, spaces)
    assert res.ok, res.message
    assert validate(payload) == []
    start = res.metrics["start"]
    assert start["positions_proposed"] == len(items) and 0 < start["positions_valid"] <= len(items)
    assert _blocked(payload, lambda p, q: q["stop_position"] < p["stop_position"]) == []


def test_bad_proposal_is_never_taken_unchecked():
    items, spaces = _items(), [van()]
    # all plants at the same spot, the last stop first, a pot on the wheel arch
    layout = StartLayout(
        sequence=[it.plant_id for it in reversed(items)],
        orientation={it.plant_id: "upright" for it in items},
        positions={it.plant_id: ("van", 290.0, 10.0, "floor") for it in items},
    )
    res = Packer(spaces, settings()).run(items, layout)
    payload = result_payload(res, spaces)
    assert validate(payload) == []  # no overlaps, nothing on the wheel arch, inside the walls
    assert res.metrics["start"]["positions_valid"] == 0
    # the loading order of the stops stays a rule: stop 1 is loaded first
    seq = [p["stop_position"] for p in sorted(payload["placements"], key=lambda p: p["sequence"])]
    assert seq == sorted(seq)


def test_modes_on_a_demo_tour(pack_owner, pack_tenant):  # noqa: F811 - fixtures from test_phase5
    p = pack_owner.post(
        "/api/plans", expect=201, json={"start_date": str(START), "days": 3, "sync": True, "pack": False}
    ).json()
    tour = pack_owner.get(f"/api/plans/{p['id']}").json()["tours"][0]
    pack_owner.put("/api/settings", json={"scope": "tenant", "key": "packing.mode", "value": "ai_start"})
    lp = pack_owner.post(f"/api/tours/{tour['id']}/load-plan").json()["plan"]
    assert lp["metrics"]["mode"] == "ai_start" and lp["metrics"]["ai"]["model"]
    assert lp["metrics"]["start"]["positions_proposed"] > 0
    assert validate(lp) == []
    pack_owner.put("/api/settings", json={"scope": "tenant", "key": "packing.mode", "value": "compare"})
    lp = pack_owner.post(f"/api/tours/{tour['id']}/load-plan").json()["plan"]
    cmp = lp["metrics"]["compare"]
    assert cmp["winner"] in ("rules", "ai_start")
    assert {"score", "violations", "seconds", "unplaced"} <= set(cmp["rules"]) <= set(cmp["ai_start"])
    assert "cost_eur" in cmp["ai_start"]
    assert validate(lp) == []
    pack_owner.put("/api/settings", json={"scope": "tenant", "key": "packing.mode", "value": "rules"})

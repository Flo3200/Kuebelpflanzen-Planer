"""Package C: vehicles by chat and by cargo-space photo (always a draft that a person confirms),
reusable modules on several vehicles, trailer combinations, module costs, AI test sets."""

from __future__ import annotations

import uuid

import pytest

from app.core.db import RlsContext, session_scope
from app.models.masterdata import Vehicle
from app.packing.service import space_from_vehicle
from tests.helpers import make_photo
from tests.test_phase3_estimates import make_order

SPRINTER = (
    "Wir haben einen Mercedes Sprinter, Kennzeichen S-GF 204. Laderaum 4,30 x 1,78 x 1,94 m, "
    "Nutzlast 1.150 kg. Die Tür ist 1,56 m breit und 1,84 m hoch. Kosten 0,32 € pro km. "
    "Regal links 120 cm lang, 40 cm tief in 90 cm Höhe."
)


def _value(draft, key, section="vehicle"):
    return draft["data"][section][key]["value"]


def test_vehicle_by_chat_draft_and_confirm(new_tenant):
    tenant, owner = new_tenant()
    d = owner.post("/api/vehicle-drafts/chat", json={"message": SPRINTER}).json()
    assert d["status"] == "open" and d["source"] == "chat"
    assert _value(d, "cargo_length_cm") == 430 and _value(d, "payload_kg") == 1150
    assert d["data"]["vehicle"]["cargo_length_cm"]["confidence"] >= 0.9
    assert _value(d, "cost_per_km", "costs") == 0.32
    assert d["messages"][-1]["role"] == "assistant" and d["messages"][-1]["text"]
    # nothing exists before the confirmation
    assert owner.get("/api/vehicles").json() == []
    r = owner.post(f"/api/vehicle-drafts/{d['id']}/confirm").json()
    v = owner.get(f"/api/vehicles/{r['vehicle_id']}").json()
    assert v["cargo_length_cm"] == 430 and v["door_height_cm"] == 184 and v["plate"] == "S-GF 204"
    settings = owner.get("/api/settings", params={"scope": "vehicle", "object_id": v["id"]}).json()["values"]
    assert next(s for s in settings if s["key"] == "costs.vehicle_per_km")["value"] == 0.32
    modules = owner.get(f"/api/vehicles/{v['id']}/modules").json()
    assert [(m["kind"], m["length_cm"], m["depth_cm"], m["height_cm"]) for m in modules] == [
        ("shelf", 120, 40, 90)
    ]
    log = owner.get("/api/audit", params={"entity": "vehicle"}).json()["items"]
    assert any(e["new_value"] and e["new_value"].get("source") == "vehicle_draft:chat" for e in log)
    owner.post(f"/api/vehicle-drafts/{d['id']}/confirm", expect=409)  # only once
    # load planning uses the result: the shelf is a loading level of the cargo space
    with session_scope(RlsContext(tenant_id=uuid.UUID(tenant["id"]))) as db:
        space = space_from_vehicle(db, db.get(Vehicle, uuid.UUID(v["id"])))
        assert space.length == 430 and [s.length for s in space.shelves] == [120]


def test_chat_asks_for_gaps_and_takes_the_answer(new_tenant):
    _, owner = new_tenant()
    d = owner.post("/api/vehicle-drafts/chat", json={"message": "Wir haben einen weißen Kastenwagen."}).json()
    assert len(d["questions"]) >= 2
    assert "vehicle.cargo_length_cm" in d["review_fields"]
    r = owner.post(f"/api/vehicle-drafts/{d['id']}/confirm", expect=400).json()
    assert r["error"]["code"] == "errors.vehicle_draft_incomplete"
    d2 = owner.post(
        "/api/vehicle-drafts/chat",
        json={
            "draft_id": d["id"],
            "message": "Laderaum 3 x 1,70 x 1,80 m, Nutzlast 1000 kg. Die Tür ist 1,50 m breit und 1,70 m hoch.",
        },
    ).json()
    assert d2["id"] == d["id"] and len(d2["messages"]) == 4
    assert _value(d2, "cargo_width_cm") == 170 and d2["questions"] == []
    owner.post(f"/api/vehicle-drafts/{d['id']}/confirm")


def test_change_existing_vehicle_by_chat(new_tenant):
    _, owner = new_tenant()
    d = owner.post("/api/vehicle-drafts/chat", json={"message": SPRINTER}).json()
    vid = owner.post(f"/api/vehicle-drafts/{d['id']}/confirm").json()["vehicle_id"]
    c = owner.post(
        "/api/vehicle-drafts/chat",
        json={"vehicle_id": vid, "message": "Die Nutzlast ist jetzt 1.000 kg, das Regal ist ausgebaut."},
    ).json()
    assert c["vehicle_id"] == vid
    assert _value(c, "cargo_length_cm") == 430  # unchanged values are kept
    assert _value(c, "payload_kg") == 1000 and c["data"]["shelves"] == []
    owner.post(f"/api/vehicle-drafts/{c['id']}/confirm")
    v = owner.get(f"/api/vehicles/{vid}").json()
    assert v["payload_kg"] == 1000 and v["cargo_length_cm"] == 430
    assert owner.get(f"/api/vehicles/{vid}/modules").json() == []
    log = owner.get("/api/audit", params={"entity": "vehicle"}).json()["items"]
    upd = next(e for e in log if e["action"] == "update" and (e["new_value"] or {}).get("payload_kg") == 1000)
    assert upd["old_value"]["payload_kg"] == 1150


def test_vehicle_from_cargo_space_photo(new_tenant):
    _, owner = new_tenant()
    d = owner.post(
        "/api/vehicle-drafts/photo",
        expect=201,
        files=[("files", ("laderaum.jpg", make_photo(a4=True), "image/jpeg"))],
        data={"note": "Nutzlast laut Fahrzeugschein 1.100 kg"},
    ).json()
    assert d["source"] == "photo" and len(d["photos"]) == 1
    width = d["data"]["vehicle"]["cargo_width_cm"]
    assert width["value"] and 0 < width["confidence"] < 0.6  # derived from the A4 scale, unsure
    assert _value(d, "payload_kg") == 1100  # stated in the note
    assert "vehicle.cargo_length_cm" in d["review_fields"] and d["questions"]
    # unsure values are corrected by hand (confidence 1) and then confirmed
    c = owner.patch(
        f"/api/vehicle-drafts/{d['id']}",
        json={"data": {"vehicle": {"cargo_length_cm": {"value": 340}, "name": {"value": "Transit"}}}},
    ).json()
    assert c["data"]["vehicle"]["cargo_length_cm"] == {"value": 340, "confidence": 1.0}
    assert "vehicle.cargo_length_cm" not in c["review_fields"]
    vid = owner.post(f"/api/vehicle-drafts/{d['id']}/confirm").json()["vehicle_id"]
    assert owner.get(f"/api/vehicles/{vid}").json()["cargo_length_cm"] == 340


def test_modules_on_several_vehicles_and_trailer_combination(new_tenant):
    tenant, owner = new_tenant()
    a = owner.post("/api/vehicles", expect=201, json={"name": "Van A", "payload_kg": 1200}).json()
    b = owner.post("/api/vehicles", expect=201, json={"name": "Van B", "payload_kg": 1200}).json()
    shelf = owner.post(
        "/api/vehicle-modules",
        expect=201,
        json={
            "name": "Regal 120",
            "kind": "shelf",
            "length_cm": 120,
            "depth_cm": 40,
            "height_cm": 90,
            "weight_kg": 25,
        },
    ).json()
    box = owner.post(
        "/api/vehicle-modules",
        expect=201,
        json={
            "name": "Werkzeugkiste",
            "kind": "fixture",
            "x_cm": 0,
            "y_cm": 100,
            "length_cm": 60,
            "depth_cm": 50,
            "height_cm": 50,
            "weight_kg": 30,
        },
    ).json()
    owner.put(f"/api/vehicles/{a['id']}/modules", json={"module_ids": [shelf["id"], box["id"]]})
    owner.put(f"/api/vehicles/{b['id']}/modules", json={"module_ids": [shelf["id"]]})
    assign = owner.get("/api/module-assignments").json()
    assert sorted(assign[shelf["id"]]) == sorted([a["id"], b["id"]]) and assign[box["id"]] == [a["id"]]
    from app.planning.inputs import vehicle_in
    from app.settings.service import SettingsResolver

    with session_scope(RlsContext(tenant_id=uuid.UUID(tenant["id"]))) as db:
        r = SettingsResolver(db, uuid.UUID(tenant["id"]))
        va, vb = (db.get(Vehicle, uuid.UUID(x["id"])) for x in (a, b))
        sa, sb = space_from_vehicle(db, va), space_from_vehicle(db, vb)
        assert [s.name for s in sa.shelves] == [s.name for s in sb.shelves] == ["Regal 120"]
        assert sa.payload == 1200 - 55 and sb.payload == 1200 - 25
        assert any(o.y0 == 100 and o.z1 == 50 for o in sa.obstacles)
        # the fixture takes floor area away in the tour planning, the shelf adds a level
        assert vehicle_in(db, r, va, [], []).area_m2 < vehicle_in(db, r, vb, [], []).area_m2
    # a trailer combined with a tow vehicle
    t = owner.post(
        "/api/vehicles", expect=201, json={"name": "Anhänger", "kind": "trailer", "required_licence": "BE"}
    ).json()
    owner.put(f"/api/vehicles/{a['id']}/trailer", json={"trailer_id": t["id"]})
    owner.put(f"/api/vehicles/{t['id']}/trailer", expect=400, json={"trailer_id": a["id"]})
    combos = owner.get("/api/vehicle-combinations").json()
    va_row = next(x for x in combos["tow_vehicles"] if x["id"] == a["id"])
    assert va_row["trailer"] == "Anhänger" and va_row["can_tow"] is True


def test_module_cost_item(new_tenant):
    _, owner = new_tenant()
    v = owner.post("/api/vehicles", expect=201, json={"name": "Van"}).json()
    m = owner.post(
        "/api/vehicle-modules",
        expect=201,
        json={"name": "Kühlbox", "kind": "fixture", "length_cm": 50, "depth_cm": 50, "height_cm": 50},
    ).json()
    owner.put(f"/api/vehicles/{v['id']}/modules", json={"module_ids": [m["id"]]})
    owner.post(
        "/api/cost-items",
        expect=201,
        json={"name": "Kühlung", "amount_eur": 1.0, "basis": "per_plant", "module_id": m["id"]},
    )
    oid = make_order(owner, weight=20, plants=2)
    costs = owner.get(f"/api/orders/{oid}/estimate").json()["costs"]
    assert {x["name"]: x["amount"] for x in costs["custom_items"]} == {"Kühlung": 2.0}


def test_eval_set_for_vehicle_chat(admin):
    sets = admin.get("/api/admin/ai/eval-sets").json()
    seeded = next(s for s in sets if s["function"] == "vehicle_chat")
    assert len(seeded["items"]) >= 3 and all(i["input_text"] for i in seeded["items"])
    fake = next(m for m in admin.get("/api/admin/ai/models").json() if m["model_name"] == "fake-1")
    runs = admin.post(
        f"/api/admin/ai/eval-sets/{seeded['id']}/run", json={"model_ids": [fake["id"]], "sync": True}
    ).json()
    metrics = runs[0]["metrics"]
    assert metrics["items"] == len(seeded["items"])
    assert metrics["mae"]["cargo_length_cm"] == pytest.approx(0, abs=1)
    assert metrics["mae"]["payload_kg"] == pytest.approx(0, abs=1)

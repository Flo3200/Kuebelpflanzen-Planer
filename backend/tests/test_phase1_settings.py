"""Settings hierarchy: override on all levels, origin, reset, undo, validation."""

from __future__ import annotations

import uuid

from app.core.context import system_actor
from app.core.db import system_session
from app.settings.registry import REGISTRY
from app.settings.service import SettingsResolver, coerce, reset, set_value


def _value(values, key):
    return next(v for v in values if v["key"] == key)


def test_three_levels_and_reset(admin, new_tenant):
    tenant, owner = new_tenant()
    key = "staff.solo_carry_kg"
    default = REGISTRY[key].default

    v = _value(owner.get("/api/settings").json()["values"], key)
    assert v["origin"] in ("default", "platform")

    # admin level
    admin.put("/api/settings", json={"scope": "platform", "key": key, "value": 27})
    v = _value(owner.get("/api/settings").json()["values"], key)
    assert v["value"] == 27 and v["origin"] == "platform" and not v["overridden_here"]

    # tenant level
    owner.put("/api/settings", json={"scope": "tenant", "key": key, "value": 22})
    v = _value(owner.get("/api/settings").json()["values"], key)
    assert v["value"] == 22 and v["origin"] == "tenant" and v["overridden_here"]
    assert v["inherited_value"] == 27

    # object level (a person) - object id need not exist for the settings layer itself
    person = uuid.uuid4()
    owner.put("/api/settings", json={"scope": "staff", "object_id": str(person), "key": key, "value": 35})
    vals = owner.get("/api/settings", params={"scope": "staff", "object_id": str(person)}).json()["values"]
    v = _value(vals, key)
    assert v["value"] == 35 and v["origin"] == "staff" and v["inherited_value"] == 22

    # reset object -> tenant value again
    owner.post("/api/settings/reset", json={"scope": "staff", "object_id": str(person), "key": key})
    v = _value(
        owner.get("/api/settings", params={"scope": "staff", "object_id": str(person)}).json()["values"], key
    )
    assert v["value"] == 22 and v["origin"] == "tenant"

    # reset tenant -> admin value
    owner.post("/api/settings/reset", json={"scope": "tenant", "key": key})
    v = _value(owner.get("/api/settings").json()["values"], key)
    assert v["value"] == 27 and v["origin"] == "platform"

    # reset admin -> registry default
    admin.post("/api/settings/reset", json={"scope": "platform", "key": key})
    v = _value(owner.get("/api/settings").json()["values"], key)
    assert v["value"] == default and v["origin"] == "default"


def test_group_and_whole_tenant_reset_and_undo(new_tenant):
    tenant, owner = new_tenant()
    owner.put("/api/settings", json={"scope": "tenant", "key": "costs.margin_pct", "value": 30})
    owner.put("/api/settings", json={"scope": "tenant", "key": "costs.overhead_pct", "value": 10})
    owner.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 40})
    obj = str(uuid.uuid4())
    owner.put(
        "/api/settings",
        json={"scope": "vehicle", "object_id": obj, "key": "costs.vehicle_per_km", "value": 0.5},
    )

    r = owner.post("/api/settings/reset", json={"scope": "tenant", "group": "costs"}).json()
    assert r["count"] == 2
    vals = owner.get("/api/settings").json()["values"]
    assert _value(vals, "costs.margin_pct")["origin"] != "tenant"
    assert _value(vals, "pricing.base_price")["value"] == 40

    # undo the group reset via the audit log
    log = owner.get("/api/audit", params={"entity": "setting"}).json()["items"]
    reset_entry = next(e for e in log if e["action"] == "reset")
    owner.post(f"/api/audit/{reset_entry['id']}/undo")
    vals = owner.get("/api/settings").json()["values"]
    assert _value(vals, "costs.margin_pct")["value"] == 30
    assert _value(vals, "costs.overhead_pct")["value"] == 10

    # whole tenant including object values
    r = owner.post("/api/settings/reset", json={"scope": "tenant", "all_scopes": True}).json()
    assert r["count"] == 4
    vals = owner.get("/api/settings", params={"scope": "vehicle", "object_id": obj}).json()["values"]
    assert _value(vals, "costs.vehicle_per_km")["origin"] in ("default", "platform")


def test_undo_single_change_and_conflict(new_tenant):
    _, owner = new_tenant()
    owner.put("/api/settings", json={"scope": "tenant", "key": "costs.margin_pct", "value": 31})
    owner.put("/api/settings", json={"scope": "tenant", "key": "costs.margin_pct", "value": 32})
    items = owner.get("/api/audit", params={"entity": "setting"}).json()["items"]
    first = next(e for e in items if e["new_value"] == {"value": 31.0})
    # undoing the older change conflicts with the newer one
    r = owner.post(f"/api/audit/{first['id']}/undo", expect=400)
    assert r.json()["error"]["code"] == "errors.undo_conflict"
    newest = next(e for e in items if e["new_value"] == {"value": 32.0})
    owner.post(f"/api/audit/{newest['id']}/undo")
    v = _value(owner.get("/api/settings").json()["values"], "costs.margin_pct")
    assert v["value"] == 31


def test_validation_and_permissions(admin, new_tenant):
    _, owner = new_tenant()
    r = owner.put(
        "/api/settings", json={"scope": "tenant", "key": "staff.solo_carry_kg", "value": 500}, expect=400
    )
    assert r.json()["error"]["code"] == "errors.setting_max"
    assert "80" in r.json()["error"]["message"]
    # tenant cannot write platform level or admin-only settings
    owner.put(
        "/api/settings", json={"scope": "platform", "key": "staff.solo_carry_kg", "value": 20}, expect=403
    )
    owner.put(
        "/api/settings", json={"scope": "tenant", "key": "billing.per_plant_eur", "value": 1}, expect=403
    )
    # unsupported level
    owner.put(
        "/api/settings",
        json={"scope": "staff", "object_id": str(uuid.uuid4()), "key": "pricing.base_price", "value": 1},
        expect=400,
    )


def test_coerce_types():
    assert coerce(REGISTRY["staff.solo_carry_kg"], "22,5") == 22.5
    assert coerce(REGISTRY["driver.qr_module"], "ja") is True
    assert coerce(REGISTRY["planning.day_start"], "06:30") == "06:30"


def test_species_chain_tenant_beats_global():
    """Object value of the tenant on a global object wins over the admin's value on the same object."""
    sys = system_actor()
    species = uuid.uuid4()
    with system_session() as db:
        from app.models.core import Tenant

        t = Tenant(name="Kettentest", slug=f"kette-{uuid.uuid4().hex[:6]}")
        db.add(t)
        db.flush()
        set_value(
            db,
            sys,
            scope="species",
            key="packing.crown_overlap",
            value=0.3,
            tenant_id=None,
            object_id=species,
        )
        r = SettingsResolver(db, t.id)
        assert r.resolve("packing.crown_overlap", ("species", species)).origin_is_global
        set_value(
            db,
            sys,
            scope="species",
            key="packing.crown_overlap",
            value=0.1,
            tenant_id=t.id,
            object_id=species,
        )
        r = SettingsResolver(db, t.id)
        res = r.resolve("packing.crown_overlap", ("plant", uuid.uuid4()), ("species", species))
        assert res.value == 0.1 and not res.origin_is_global
        reset(db, sys, scope="species", tenant_id=None, object_id=species)

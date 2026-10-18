"""Package B: species in the background. Tenants no longer maintain species; the AI names the species
and its properties on the plant, missing ones come from the internal knowledge base."""

from __future__ import annotations

import uuid
from datetime import date

from app.core.db import RlsContext, session_scope
from app.models.orders import Plant
from app.planning.inputs import frost_safe_from
from app.settings.service import SettingsResolver
from app.timemodel.estimate import Estimator
from tests.test_phase3_estimates import make_order


def test_species_management_is_admin_only(admin, new_tenant):
    _, owner = new_tenant()
    owner.get("/api/species", expect=403)
    owner.post("/api/species", expect=403, json={"name": "Meine Art"})
    catalog = admin.get("/api/species").json()
    olive = next(s for s in catalog if s["name"] == "Olivenbaum")
    owner.patch(f"/api/species/{olive['id']}", expect=403, json={"plant_kg_per_l": 0.05})
    # species-level settings belong to the knowledge base too
    owner.put(
        "/api/settings",
        expect=403,
        json={"scope": "species", "object_id": olive["id"], "key": "packing.crown_overlap", "value": 0.3},
    )
    # the plant form offers a species name, not a link to the species table
    meta = {f["name"]: f for f in owner.get("/api/meta/entities/plant").json()["fields"]}
    assert meta["species_name"]["writable"] and not meta["species_id"]["writable"]


def test_plant_gets_properties_from_knowledge_base(new_tenant):
    _, owner = new_tenant()
    oid = make_order(owner, plants=0)
    p = owner.post(
        f"/api/orders/{oid}/plants",
        expect=201,
        json={"species_name": "Zitronenbaum", "pot_diameter_cm": 50, "pot_height_cm": 45},
    ).json()
    assert p["species_name"] == "Zitronenbaum" and p["species_source"] == "person"
    assert p["species_id"] is not None  # linked to the knowledge base
    assert p["frost_sensitive"] is True  # citrus is tender
    for field in ("tip_tendency", "compressibility", "soil_kg_per_l", "plant_kg_per_l", "trunk_kg_per_m"):
        assert p[field] is not None and field in p["estimated_fields"], field
    # an unknown species still gets usable defaults
    q = owner.post(f"/api/orders/{oid}/plants", expect=201, json={"species_name": "Fantasiepflanze"}).json()
    assert q["species_id"] is None and q["tip_tendency"] is not None and q["frost_sensitive"] is False
    # renaming the species re-derives the estimated properties
    r = owner.patch(f"/api/plants/{p['id']}", json={"species_name": "Olivenbaum"}).json()
    assert r["frost_sensitive"] is False and r["species_source"] == "person"


def test_weight_and_frost_rule_read_the_plant(new_tenant):
    tenant, owner = new_tenant()
    oid = make_order(owner, plants=0)
    base = {"species_name": "Olivenbaum", "pot_diameter_cm": 60, "pot_height_cm": 55}
    light = owner.post(f"/api/orders/{oid}/plants", expect=201, json=base).json()
    heavy = owner.post(f"/api/orders/{oid}/plants", expect=201, json={**base, "soil_kg_per_l": 2.0}).json()
    assert heavy["weight_kg"] > light["weight_kg"] * 1.2
    # a citrus marked as not frost sensitive by a person is not held back by the frost rule
    lemon = owner.post(
        f"/api/orders/{oid}/plants",
        expect=201,
        json={"species_name": "Zitronenbaum", "frost_sensitive": False},
    ).json()
    assert lemon["frost_sensitive"] is False and "frost_sensitive" not in lemon["estimated_fields"]
    tid = uuid.UUID(tenant["id"])
    with session_scope(RlsContext(tenant_id=tid)) as db:
        plants = [db.get(Plant, uuid.UUID(x)) for x in (light["id"], lemon["id"])]
        est = Estimator(db, tid)
        r = SettingsResolver(db, tid)
        assert frost_safe_from(r, plants, date(2027, 4, 1), est) is None
        plants[1].frost_sensitive = True
        assert frost_safe_from(r, plants, date(2027, 4, 1), est) == date(2027, 5, 15)
        db.rollback()


def test_ai_intake_stores_species_and_properties(new_tenant):
    _, owner = new_tenant()
    msg = (
        "Guten Tag, ich bin Klara Berg, Rosenweg 3, 70180 Stuttgart, Tel. 0711 5551234. "
        "Bitte holen Sie meinen Zitronenbaum ab, etwa 1,40 m hoch im 45 cm Topf, er ist frostempfindlich. "
        "Dazu ein Oleander, 1,60 m hoch."
    )
    draft = owner.post(
        "/api/drafts", expect=201, data={"text": msg, "source_kind": "email", "sync": "true"}
    ).json()
    plants = draft["extracted"]["plants"]
    lemon = next(p for p in plants if p["species"]["value"] == "Zitronenbaum")
    assert lemon["frost_sensitive"] == {"value": True, "confidence": 0.9}
    assert lemon["tip_tendency"]["value"] is not None  # from the catalog, moderate confidence
    # background properties are not review fields
    assert not any(k.endswith(("tip_tendency", "compressibility")) for k in draft["review_fields"])
    result = owner.post(f"/api/drafts/{draft['id']}/confirm", json={}).json()
    order = owner.get(f"/api/orders/{result['order_id']}").json()
    lp = next(p for p in order["plants"] if p["species_name"] == "Zitronenbaum")
    assert lp["species_source"] == "ai" and lp["frost_sensitive"] is True
    assert (
        lp["field_confidence"]["frost_sensitive"] == 0.9 and "frost_sensitive" not in lp["estimated_fields"]
    )
    assert lp["field_confidence"]["tip_tendency"] < 0.6 and "tip_tendency" in lp["estimated_fields"]

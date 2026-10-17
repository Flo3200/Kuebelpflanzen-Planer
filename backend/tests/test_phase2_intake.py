"""Phase 2 acceptance: a pasted message with photos becomes a draft with confidences;
after confirmation customer, order and plants exist."""

from __future__ import annotations

import io

from PIL import Image

from tests.helpers import make_photo

MESSAGE = """Hallo liebe Gärtnerei,

wir möchten dieses Jahr wieder unsere Kübelpflanzen bei Ihnen überwintern lassen.
Es sind zwei Oleander, ca. 1,60 m hoch im Topf mit 50 cm Durchmesser, und ein Olivenbaum,
etwa 2 m hoch, Kübel 70 cm, der ist schwer, ich schätze 90 kg.
Die Pflanzen stehen auf unserer Dachterrasse im 3. Stock, es gibt leider keinen Aufzug,
die Treppe hat 54 Stufen. Vom Haus bis zur Straße sind es ca. 15 m.
Abholung bitte zwischen dem 20. und 31.10.

Viele Grüße
Petra Sommer
Hauptstraße 12, 70563 Stuttgart
Tel. 0711 1234567, petra.sommer@example.com
"""


def _upload_files():
    return [
        ("files", ("front.jpg", make_photo(a4=True), "image/jpeg")),
        ("files", ("side.jpg", make_photo(a4=True), "image/jpeg")),
        ("files", ("blurry.jpg", make_photo(a4=False, blur=True), "image/jpeg")),
    ]


def test_message_with_photos_becomes_draft_and_records(new_tenant):
    _, owner = new_tenant()
    r = owner.post(
        "/api/drafts",
        expect=201,
        data={
            "text": MESSAGE,
            "source_kind": "email",
            "sync": "true",
            "kinds": ["plant_front", "plant_side", "pot"],
        },
        files=_upload_files(),
    ).json()
    assert r["status"] == "review", r
    ex = r["extracted"]
    assert ex["customer"]["name"]["value"] == "Petra Sommer"
    assert ex["customer"]["email"]["value"] == "petra.sommer@example.com"
    assert ex["customer"]["email"]["confidence"] > 0.9
    assert ex["address"]["postal_code"]["value"] == "70563"
    assert ex["address"]["street"]["value"].startswith("Hauptstraße 12")
    plants = ex["plants"]
    oleander = next(p for p in plants if p["species"]["value"] == "Oleander")
    assert oleander["count"]["value"] == 2
    assert oleander["total_height_cm"]["value"] == 160
    assert oleander["pot_diameter_cm"]["value"] == 50
    olive = next(p for p in plants if p["species"]["value"] == "Olivenbaum")
    assert olive["weight_kg"]["value"] == 90
    assert ex["path"]["steps"]["value"] == 54
    assert ex["path"]["elevator"]["value"] is False
    assert ex["path"]["length_m"]["value"] == 15
    assert ex["order"]["earliest_date"]["value"].endswith("-10-20")
    # every value carries a confidence; uncertain ones are flagged for review
    assert all(0 <= c <= 1 for c in r["confidence"].values())
    assert r["review_fields"], "some fields must be marked for review"
    # photo check: local A4 detection and blur detection
    assert len(r["photos"]) == 3
    assert r["photos"][0]["a4_detected"] is True
    assert r["photos"][2]["quality"]["sharp"] is False
    assert any("unscharf" in f for f in r["photo_check"]["feedback"])
    assert r["follow_up"]

    # human corrects the weight confidence (edits the value) and confirms
    ex["plants"][1]["weight_kg"] = {"value": 95, "confidence": 1.0}
    result = owner.post(f"/api/drafts/{r['id']}/confirm", json={"extracted": ex}).json()
    assert result["customer_created"] is True
    order = owner.get(f"/api/orders/{result['order_id']}").json()
    assert order["order"]["status"] == "confirmed"
    assert order["customer"]["name"] == "Petra Sommer"
    assert order["customer"]["consent_photos"] is True
    assert len(order["plants"]) == 3  # 2 oleander + 1 olive
    olive_plant = next(p for p in order["plants"] if p["species_name"] == "Olivenbaum")
    assert olive_plant["weight_kg"] == 95
    assert "weight_kg" not in olive_plant["estimated_fields"]
    oleanders = [p for p in order["plants"] if p["species_name"] == "Oleander"]
    assert all(p["weight_kg"] and "weight_kg" in p["estimated_fields"] for p in oleanders)
    path = order["paths"][0]
    assert path["summary"]["steps"] == 54 and path["summary"]["length_m"] == 15
    assert len(order["photos"]) == 3
    # the draft is closed and cannot be confirmed twice
    assert owner.get(f"/api/drafts/{r['id']}").json()["status"] == "confirmed"
    owner.post(f"/api/drafts/{r['id']}/confirm", json={}, expect=400)
    # a second message from the same customer reuses the customer
    r2 = owner.post(
        "/api/drafts",
        expect=201,
        data={
            "text": "Noch eine Palme, 1,5 m. Gruß Petra Sommer, petra.sommer@example.com, Hauptstraße 12, 70563 Stuttgart",
            "sync": "true",
        },
    ).json()
    res2 = owner.post(f"/api/drafts/{r2['id']}/confirm", json={}).json()
    assert res2["customer_created"] is False and res2["customer_id"] == result["customer_id"]


def test_ai_usage_is_recorded(new_tenant):
    _, owner = new_tenant()
    owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"})
    usage = owner.get("/api/ai/usage").json()
    assert any(r["function"] == "message_intake" and r["calls"] >= 1 for r in usage["rows"])
    assert usage["status"]["blocked"] is False


def test_spending_limit_blocks(admin, new_tenant):
    t, owner = new_tenant()
    admin.put(
        "/api/settings",
        json={"scope": "tenant", "tenant_id": t["id"], "key": "ai.monthly_limit_eur", "value": 0.0000001},
    )
    # the fake model is free, so simulate earlier spending
    from app.core.db import system_session
    from app.models.ai import AIUsage

    with system_session() as db:
        db.add(AIUsage(tenant_id=t["id"], function="message_intake", provider="x", model="x", cost_eur=1.0))
    r = owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}).json()
    assert r["status"] == "failed" and r["error"] == "errors.ai_limit"


def test_exif_and_gps_are_removed(new_tenant):
    _, owner = new_tenant()
    r = owner.post(
        "/api/drafts",
        expect=201,
        data={"text": "Foto"},
        files=[("files", ("gps.jpg", make_photo(gps=True), "image/jpeg"))],
    ).json()
    raw = owner.get(r["photos"][0]["url"]).content
    with Image.open(io.BytesIO(raw)) as img:
        assert len(img.getexif()) == 0


def test_photo_requires_consent_for_orders(new_tenant):
    _, owner = new_tenant()
    c = owner.post("/api/customers", expect=201, json={"name": "Kunde ohne Einwilligung"}).json()
    a = owner.post(
        "/api/addresses",
        expect=201,
        json={"customer_id": c["id"], "street": "Weg 1", "postal_code": "70000", "city": "Stuttgart"},
    ).json()
    o = owner.post("/api/orders", expect=201, json={"customer_id": c["id"], "address_id": a["id"]}).json()
    files = {"file": ("p.jpg", make_photo(), "image/jpeg")}
    r = owner.post(
        "/api/photos", expect=409, data={"order_id": o["order"]["id"], "kind": "plant_front"}, files=files
    )
    assert r.json()["error"]["code"] == "errors.consent_missing"
    owner.post(
        "/api/photos",
        expect=201,
        data={"order_id": o["order"]["id"], "kind": "plant_front", "consent_confirmed": "true"},
        files={"file": ("p.jpg", make_photo(), "image/jpeg")},
    )
    assert owner.get(f"/api/customers/{c['id']}").json()["consent_photos"] is True

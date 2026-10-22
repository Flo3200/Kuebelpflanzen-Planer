"""Round 2, package I/J/Q: photos pasted without kinds are sorted by the AI and assigned to plants,
missing photos create a notification with a ready message; contact data only on request; customer
link for photos and location."""

from __future__ import annotations

from tests.helpers import make_photo, set_modules

MESSAGE = """Guten Tag, wir haben zwei Pflanzen zum Überwintern: einen Oleander, 1,60 m hoch,
Topf 50 cm, und einen Olivenbaum, 2 m hoch, Kübel 70 cm.
Vom Garten bis zur Straße sind es ca. 20 m.
Viele Grüße
Petra Sommer
Hauptstraße 12, 70563 Stuttgart
Tel. 0711 1234567, petra.sommer@example.com
"""


def _photos(n: int = 3, landscape: int = 1):
    files = [("files", (f"p{i}.jpg", make_photo(a4=True), "image/jpeg")) for i in range(n)]
    files += [
        ("files", (f"weg{i}.jpg", make_photo(a4=False, size=(1200, 800)), "image/jpeg"))
        for i in range(landscape)
    ]
    return files


def test_pasted_photos_are_sorted_and_assigned(new_tenant):
    _, owner = new_tenant()
    d = owner.post(
        "/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}, files=_photos(4, 1)
    ).json()
    assert d["status"] == "review", d
    kinds = [p["kind"] for p in d["photos"]]
    assert kinds[-1] == "path_start"  # landscape without A4 sheet = path
    plants = [p["ai_results"]["sorted"]["plant"] for p in d["photos"][:4]]
    assert plants == [1, 1, 2, 2]
    assert kinds[:2] == ["plant_front", "plant_side"]
    # incomplete set per plant: notification with a message for the customer
    full = owner.get(f"/api/drafts/{d['id']}").json()
    n = full["notification"]
    assert n and n["kind"] == "photos_missing" and not n["done"]
    assert "Oleander" in n["message"] and "Petra Sommer" in n["message"]
    assert full["follow_up"] == n["message"]
    assert full["store_contact_default"] is False
    bell = owner.get("/api/notifications").json()
    assert bell["unread"] == 1 and bell["items"][0]["draft_id"] == d["id"]
    # reprocessing updates the same notification instead of adding one
    owner.post(f"/api/drafts/{d['id']}/reprocess", params={"sync": "true"})
    assert len(owner.get("/api/notifications").json()["items"]) == 1

    res = owner.post(f"/api/drafts/{d['id']}/confirm", json={}).json()
    order = owner.get(f"/api/orders/{res['order_id']}").json()
    by_plant = {}
    for ph in order["photos"]:
        by_plant.setdefault(ph["plant_id"], []).append(ph["kind"])
    oleander = next(p for p in order["plants"] if p["species_name"] == "Oleander")
    olive = next(p for p in order["plants"] if p["species_name"] == "Olivenbaum")
    assert len(by_plant[oleander["id"]]) == 2 and len(by_plant[olive["id"]]) == 2
    assert by_plant[None] == ["path_start"]
    # contact data is not stored by default
    assert order["customer"]["phone"] is None and order["customer"]["email"] is None
    # the notification now points at the order as well
    assert owner.get("/api/notifications").json()["items"][0]["order_id"] == res["order_id"]


def test_contact_data_only_on_request(new_tenant):
    _, owner = new_tenant()
    d = owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}).json()
    res = owner.post(f"/api/drafts/{d['id']}/confirm", json={"store_contact": True}).json()
    c = owner.get(f"/api/orders/{res['order_id']}").json()["customer"]
    assert c["phone"] and c["email"] == "petra.sommer@example.com"
    # with the setting on, contact data is taken by default
    owner.put("/api/settings", json={"scope": "tenant", "key": "privacy.store_contact", "value": True})
    d2 = owner.post(
        "/api/drafts", expect=201, data={"text": MESSAGE.replace("Petra", "Paula"), "sync": "true"}
    ).json()
    res2 = owner.post(f"/api/drafts/{d2['id']}/confirm", json={}).json()
    assert owner.get(f"/api/orders/{res2['order_id']}").json()["customer"]["phone"]


def test_no_notification_when_complete_or_switched_off(new_tenant):
    _, owner = new_tenant()
    owner.put("/api/settings", json={"scope": "tenant", "key": "notify.missing_photos", "value": False})
    owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"})
    assert owner.get("/api/notifications").json()["items"] == []


def test_customer_link_photos_and_location(new_tenant, make_client):
    _, owner = new_tenant()
    set_modules(owner, share=True)
    d = owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}).json()
    n = owner.get(f"/api/drafts/{d['id']}").json()["notification"]
    url = n["data"]["share_url"]
    assert url and url in n["message"]
    token = url.rsplit("/", 1)[1]

    customer = make_client()  # no login
    view = customer.get(f"/api/share/{token}").json()
    assert view["needed"] and view["consent_given"] is False
    customer.post(f"/api/share/{token}/photos", expect=409, files=_photos(1, 0))
    customer.post(f"/api/share/{token}/consent", json={"accept": True})
    up = customer.post(f"/api/share/{token}/photos", expect=201, files=_photos(2, 0)).json()
    assert up["received"] == 2
    customer.put(f"/api/share/{token}/location", json={"lat": 48.73, "lon": 9.11, "note": "Tor hinten"})
    customer.get("/api/share/not-a-token", expect=404)

    kinds = {n["kind"] for n in owner.get("/api/notifications").json()["items"]}
    assert "customer_upload" in kinds
    # the draft is evaluated again with the new photos (background job)
    from app.jobs.queue import run_pending

    run_pending()
    d2 = owner.get(f"/api/drafts/{d['id']}").json()
    assert len(d2["photos"]) == 2 and d2["status"] == "review"
    res = owner.post(f"/api/drafts/{d['id']}/confirm", json={}).json()
    order = owner.get(f"/api/orders/{res['order_id']}").json()
    assert order["address"]["lat"] == 48.73 and order["address"]["geocode_source"] == "customer"
    # links of a tenant without the module do not work
    set_modules(owner, share=False)
    customer.get(f"/api/share/{token}", expect=409)

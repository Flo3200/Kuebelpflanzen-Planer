"""Round 2, packages M and L: spontaneous teams from a sentence, voice control (test model)."""

from __future__ import annotations

from datetime import date, timedelta

from tests.test_phase3_estimates import make_order


def _staff(owner):
    for name in ("Lea Roth", "Tom Berger", "Max Kunz"):
        owner.post("/api/staff", expect=201, json={"name": name, "licences": ["B"]})
    owner.post("/api/vehicles", expect=201, json={"name": "Sprinter weiß"})
    owner.post("/api/vehicles", expect=201, json={"name": "Kofferanhänger", "kind": "trailer"})


def test_spontaneous_team_from_sentence(new_tenant):
    _, owner = new_tenant()
    _staff(owner)
    p = owner.post(
        "/api/teams/spontaneous/parse", json={"text": "Morgen fahren Lea und Tom mit dem Sprinter"}
    ).json()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert p["date"] == tomorrow
    assert sorted(p["members"]) == ["Lea Roth", "Tom Berger"]
    assert p["vehicle"] == "Sprinter weiß"
    team = owner.post(
        "/api/teams/spontaneous", expect=201, json={"text": "Morgen fahren Lea und Tom mit dem Sprinter"}
    ).json()
    teams = owner.get("/api/teams").json()
    row = next(x for x in teams if x["id"] == team["id"])
    assert row["ad_hoc"] is True and row["valid_from"] == tomorrow and row["valid_to"] == tomorrow
    assert len(row["member_ids"]) == 2 and row["vehicle_id"]
    kinds = [n["kind"] for n in owner.get("/api/notifications").json()["items"]]
    assert "team_created" in kinds
    # without a day nothing is created
    owner.post("/api/teams/spontaneous", expect=422, json={"text": "Lea und Tom"})
    # unknown people are reported, known ones taken
    p2 = owner.post("/api/teams/spontaneous/parse", json={"text": "Am Freitag fahren Max und Susi"}).json()
    assert p2["members"] == ["Max Kunz"] and date.fromisoformat(p2["date"]).weekday() == 4


def test_day_team_is_used_by_the_planning(new_tenant):
    _, owner = new_tenant()
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.form_teams", "value": "fixed"})
    owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    _staff(owner)
    oid = make_order(owner, weight=20, plants=1)
    owner.patch(f"/api/orders/{oid}", json={"status": "confirmed"})
    day = date.today() + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    staff = owner.get("/api/staff").json()
    ids = [s["id"] for s in staff if s["name"] in ("Lea Roth", "Tom Berger")]
    owner.post("/api/teams/spontaneous", expect=201, json={"date": day.isoformat(), "member_ids": ids})
    plan = owner.post(
        "/api/plans", expect=201, json={"start_date": day.isoformat(), "days": 1, "sync": True, "pack": False}
    ).json()
    detail = owner.get(f"/api/plans/{plan['id']}").json()
    tours = detail["tours"]
    names = sorted(m["name"] if isinstance(m, dict) else m for m in tours[0]["members"])
    assert tours and names == ["Lea Roth", "Tom Berger"]


def test_voice_commands_with_test_model(new_tenant):
    _, owner = new_tenant()
    _staff(owner)
    cfg = owner.get("/api/voice/config").json()
    assert cfg == {"enabled": True, "transcription": "browser"}
    r = owner.post("/api/voice/command", json={"text": "Öffne die Planung"}).json()
    assert r["actions"] == [{"type": "navigate", "to": "/betrieb/planung"}]
    r = owner.post("/api/voice/command", json={"text": "Tabellen"}).json()
    assert r["actions"][0]["to"] == "/betrieb/tabellen"
    r = owner.post("/api/voice/command", json={"text": "Morgen fahren Lea und Max mit dem Sprinter"}).json()
    assert r["changes"][0]["kind"] == "team" and "angelegt" in r["text"]
    r = owner.post(
        "/api/voice/command",
        json={
            "text": "Neue Nachricht: Frau Sommer hat zwei Oleander, 1,60 m hoch, Hauptstraße 12, 70563 Stuttgart"
        },
    ).json()
    assert r["changes"][0]["kind"] == "draft" and r["actions"][0]["to"].startswith("/betrieb/posteingang/")
    draft = owner.get(r["actions"][0]["to"].replace("/betrieb/posteingang/", "/api/drafts/")).json()
    assert draft["source_kind"] == "voice" and "Oleander" in draft["source_text"]
    r = owner.post("/api/voice/command", json={"text": "Welche Touren sind morgen?"}).json()
    assert "keine Touren" in r["text"]
    r = owner.post("/api/voice/command", json={"text": "Setze die höchste Teamgröße auf 5"}).json()
    assert r["changes"] and r["changes"][0]["new"] == 5  # the test model only matches words roughly
    r = owner.post("/api/voice/command", json={"text": "Bla bla"}).json()
    assert r["actions"] == [] and "nicht verstanden" in r["text"]
    # transcription needs a real model
    owner.post("/api/voice/transcribe", expect=400, files={"audio": ("a.webm", b"x", "audio/webm")})
    owner.put("/api/settings", json={"scope": "tenant", "key": "voice.enabled", "value": False})
    owner.post("/api/voice/command", expect=409, json={"text": "Öffne die Planung"})

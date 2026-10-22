"""Round 2, package N: two AI models discuss the time formula; the proposal is valid, evaluated on the
measurements and can be adopted as a new formula version."""

from __future__ import annotations

from tests.test_phase6_field import field_tenant, owner  # noqa: F401  (demo tenant with orders)


def test_debate_with_measurements_and_adopt(owner):  # noqa: F811
    owner.post("/api/learning/synthetic", json={"n": 40, "seed": 9})
    models = owner.get("/api/formula-debates/models").json()
    fake = next(m for m in models if m["kind"] == "fake")
    d = owner.post(
        "/api/formula-debates",
        expect=201,
        json={
            "model_a_id": fake["id"],
            "model_b_id": fake["id"],
            "n_rounds": 2,
            "sync": True,
            "question": "Brauchen wir eine Zeit je Stufe?",
        },
    ).json()
    assert d["status"] == "done", d
    assert len(d["rounds"]) == 4
    assert [r["speaker"] for r in d["rounds"]] == ["a", "b", "a", "b"]
    assert d["rounds"][-1]["agree"] is True
    p = d["proposal"]
    assert p["valid"] is True, p
    work = next(e for e in p["expressions"] if e["name"] == "work")
    assert "h_fix" in work["expr"] and "k_steps" in work["expr"]
    ev = d["evaluation"]
    assert ev["n"] > 0 and "mae" in ev["current"] and "mae" in ev["proposed_start"]
    assert "proposed_fitted" in ev
    listed = owner.get("/api/formula-debates").json()
    assert listed[0]["id"] == d["id"]
    r = owner.post(f"/api/formula-debates/{d['id']}/adopt").json()
    assert r["version"] >= 1 and r["debate"]["adopted_version_id"] == r["version_id"]
    formulas = owner.get("/api/formulas", params={"key": "time"}).json()
    assert "h_fix" in str(formulas)


def test_debate_without_measurements(new_tenant):
    _, api = new_tenant()
    d = api.post("/api/formula-debates", expect=201, json={"n_rounds": 1, "sync": True}).json()
    assert d["status"] == "done" and len(d["rounds"]) == 2
    assert d["proposal"]["valid"] is True and d["evaluation"] == {"n": 0}

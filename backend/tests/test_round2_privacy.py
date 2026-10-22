"""Round 2, package J: overview of stored personal data, removing all contact data, original messages
of handled drafts are emptied after the period."""

from __future__ import annotations

from datetime import date, timedelta

from tests.test_round2_inbox import MESSAGE


def test_overview_and_remove_contacts(new_tenant):
    _, owner = new_tenant()
    d = owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}).json()
    owner.post(f"/api/drafts/{d['id']}/confirm", json={"store_contact": True})
    o = owner.get("/api/privacy/overview").json()
    assert o["customers"] == 1 and o["with_phone"] == 1 and o["with_email"] == 1
    assert o["drafts_with_text"] == 1 and o["settings"]["privacy.store_contact"] is False
    assert owner.post("/api/privacy/remove-contacts").json()["customers"] == 1
    o = owner.get("/api/privacy/overview").json()
    assert o["with_phone"] == 0 and o["with_email"] == 0
    # the draft no longer carries the contact values either
    ex = owner.get(f"/api/drafts/{d['id']}").json()["extracted"]
    assert ex["customer"]["phone"]["value"] is None


def test_draft_texts_are_emptied_after_period(new_tenant):
    t, owner = new_tenant()
    d = owner.post("/api/drafts", expect=201, data={"text": MESSAGE, "sync": "true"}).json()
    owner.post(f"/api/drafts/{d['id']}/confirm", json={})
    from app.core.context import system_actor
    from app.core.db import system_session
    from app.privacy.service import run_retention

    with system_session() as db:
        out = run_retention(db, system_actor(t["id"]), t["id"])
        assert out["draft_texts"] == 0  # still within the period
        out = run_retention(db, system_actor(t["id"]), t["id"], today=date.today() + timedelta(days=61))
        assert out["draft_texts"] == 1
    dd = owner.get(f"/api/drafts/{d['id']}").json()
    assert dd["source_text"] == "" and dd["follow_up"] is None
    assert dd["extracted"]["customer"]["email"]["value"] is None

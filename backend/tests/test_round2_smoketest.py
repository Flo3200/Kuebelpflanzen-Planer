"""Round 2, package S: the AI function test runs every AI function once (test model without keys)."""

from __future__ import annotations


def test_smoketest_with_test_model(admin):
    r = admin.post("/api/admin/ai/smoketest", json={"sync": True}).json()
    assert r["status"] == "done", r
    rows = {x["function"]: x for x in r["result"]["rows"]}
    for fn in (
        "message_intake",
        "photo_sort",
        "completeness_check",
        "photo_analysis",
        "follow_up",
        "team_parse",
        "vehicle_chat",
        "formula_debate",
        "voice_command",
        "settings_assistant",
        "plant_image",
    ):
        assert rows[fn]["ok"], rows[fn]
    # speech to text needs an OpenAI model: reported, not hidden
    assert rows["transcribe"]["ok"] is False and rows["transcribe"]["error"]
    # the OpenAI models are prepared (provider off until the admin enters a key)
    models = {m["model_name"] for m in admin.get("/api/admin/ai/models").json()}
    assert {"gpt-5", "gpt-image-1", "gpt-4o-transcribe"} <= models

"""AI load arrangement (package G).

The AI (function load_layout) proposes a loading order, orientation and position per plant from the
cargo-space geometry, the plant list and the tour order. The proposal is never taken over unchecked:
the packer uses it as start solution, checks every rule (rigid pots, crowns, wheel arches, shelves,
tipping, centre of gravity, axle and tongue loads, heavy plants, loading order) and improves it.

packing.mode: rules (default) – only the rule-based packer; ai_start – AI proposal as start;
compare – both, the better result wins and both are logged in the load plan.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.packing.geometry import PlantItem, Space
from app.packing.packer import PackResult, StartLayout

ORIENTATIONS = ("upright", "lying_x", "lying_y", "tilted_x")


def request_context(spaces: list[Space], items: list[PlantItem], direction: str) -> dict[str, Any]:
    return {
        "direction": direction,
        "spaces": [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "length": s.length,
                "width": s.width,
                "height": s.height,
                "door_w": s.door_w,
                "door_h": s.door_h,
                "payload": s.payload,
                "obstacles": [o.__dict__ for o in s.obstacles],
                "shelves": [
                    {
                        "id": sh.id,
                        "x0": sh.x0,
                        "y0": sh.y0,
                        "length": sh.length,
                        "depth": sh.depth,
                        "z": sh.z,
                        "clearance": sh.clearance,
                        "max_load": sh.max_load,
                    }
                    for sh in s.shelves
                ],
                "front_axle_x": s.front_axle_x,
                "rear_axle_x": s.rear_axle_x,
            }
            for s in spaces
        ],
        "plants": [
            {
                "plant_id": it.plant_id,
                "number": it.number,
                "stop": it.stop_position,
                "weight": round(it.weight, 1),
                "pot": round(it.pot_d, 1),
                "pot_h": round(it.pot_h, 1),
                "height": round(it.total_h, 1),
                "crown_w": round(it.crown_w, 1),
                "can_tilt": it.can_tilt,
                "sensitive": it.sensitive,
                "tip_tendency": round(it.tip_tendency, 2),
            }
            for it in items
        ],
    }


def request_text(ctx: dict[str, Any]) -> str:
    order = (
        "Abholung: Stopp 1 wird zuerst eingeladen und steht ganz vorn an der Stirnwand, der letzte Stopp an der Tür."
        if ctx["direction"] == "pickup"
        else "Rücklieferung: der erste Stopp wird zuletzt eingeladen und steht an der Tür."
    )
    return f"{order}\nLaderäume und Pflanzen (JSON):\n" + json.dumps(ctx, ensure_ascii=False)


def parse_layout(data: dict[str, Any], items: list[PlantItem], spaces: list[Space]) -> StartLayout:
    """Proposal of the AI -> start layout; unknown plants, spaces or orientations are dropped."""
    known = {it.plant_id for it in items}
    space_ids = {s.id for s in spaces}
    levels = {sh.id for s in spaces for sh in s.shelves} | {"floor"}
    layout = StartLayout(source="ai")
    for p in data.get("placements") or []:
        pid = str(p.get("plant_id") or "")
        if pid not in known or pid in layout.orientation:
            continue
        layout.sequence.append(pid)
        o = str(p.get("orientation") or "upright")
        layout.orientation[pid] = o if o in ORIENTATIONS else "upright"
        sid, level = str(p.get("space_id") or ""), str(p.get("level") or "floor")
        try:
            x, y = float(p["x_cm"]), float(p["y_cm"])
        except (KeyError, TypeError, ValueError):
            continue
        if sid in space_ids and level in levels:
            layout.positions[pid] = (sid, x, y, level)
    return layout


def ai_layout(
    db: Session, tenant_id: uuid.UUID, spaces: list[Space], items: list[PlantItem], direction: str
) -> tuple[StartLayout, dict[str, Any]]:
    from sqlalchemy import func, select

    from app.ai import service as ai
    from app.models.ai import AIUsage

    ctx = request_context(spaces, items, direction)
    marker = uuid.uuid4()
    t0 = time.monotonic()
    resp, model = ai.call(db, tenant_id, "load_layout", request_text(ctx), context=ctx, job_id=marker)
    cost = (
        db.scalar(select(func.coalesce(func.sum(AIUsage.cost_eur), 0)).where(AIUsage.job_id == marker)) or 0
    )
    info = {
        "model": model.label,
        "seconds": round(time.monotonic() - t0, 2),
        "cost_eur": round(float(cost), 4),
    }
    return parse_layout(resp.data or {}, items, spaces), info


def better(a: PackResult, b: PackResult) -> bool:
    """a better than b: valid first, then fewer unplaced plants, then the lower score."""
    return (not a.ok, len(a.unplaced), a.score) < (not b.ok, len(b.unplaced), b.score)


def summary(res: PackResult) -> dict[str, Any]:
    return {
        "ok": res.ok,
        "score": round(res.score, 1),
        "unplaced": len(res.unplaced),
        "violations": len(res.violations),
        "seconds": res.metrics.get("seconds"),
        "iterations": res.iterations,
    }


def pack_with_mode(
    db: Session, tenant_id: uuid.UUID, mode: str, spaces: list[Space], items: list[PlantItem], make_packer
) -> PackResult:
    """Runs the packer according to packing.mode. make_packer() returns a fresh Packer."""
    if mode not in ("ai_start", "compare"):
        return make_packer().run(items)
    rules = make_packer().run(items) if mode == "compare" else None
    try:
        layout, info = ai_layout(db, tenant_id, spaces, items, make_packer().s.direction)
    except Exception as exc:  # noqa: BLE001 - AI not available: the rules decide
        res = rules or make_packer().run(items)
        res.metrics["ai_error"] = getattr(exc, "code", type(exc).__name__)
        return res
    with_ai = make_packer().run(items, layout)
    with_ai.metrics["ai"] = info
    if rules is None:
        with_ai.metrics["mode"] = "ai_start"
        return with_ai
    winner = with_ai if better(with_ai, rules) else rules
    winner.metrics["mode"] = "compare"
    winner.metrics["compare"] = {
        "rules": summary(rules),
        "ai_start": {**summary(with_ai), **info, "start": with_ai.metrics.get("start")},
        "winner": "ai_start" if winner is with_ai else "rules",
    }
    return winner


def fake_layout(context: dict[str, Any]) -> dict[str, Any]:
    """Test model: fills the floor row by row in loading order (no AI, but plausible positions)."""
    spaces = context.get("spaces") or []
    if not spaces:
        return {"placements": [], "notes": "kein Laderaum"}
    sp = spaces[0]
    plants = sorted(
        context.get("plants") or [],
        key=lambda p: (p["stop"] if context.get("direction") == "pickup" else -p["stop"], -p["weight"]),
    )
    out = []
    x, y, row = 2.0, 2.0, 0.0
    for p in plants:
        lying = p["height"] > sp["height"] - 5 and p["can_tilt"]
        # room for the crown (it may overlap its neighbours only a little) plus a small gap
        crown = max(p["pot"], p["crown_w"] * 0.9)
        if lying:
            length, width = p["height"], max(p["pot"], p["crown_w"] * 0.7) + 3
        else:
            length = width = crown + 3
        if y + width > sp["width"]:
            x, y, row = x + row + 2, 2.0, 0.0
        cx, cy = x + length / 2, y + width / 2
        out.append(
            {
                "plant_id": p["plant_id"],
                "space_id": sp["id"],
                "level": "floor",
                "orientation": "lying_x" if lying else "upright",
                "x_cm": round(cx, 1),
                "y_cm": round(cy, 1),
            }
        )
        y += width + 2
        row = max(row, length)
    return {"placements": out, "notes": "Testmodell: Reihen nach Ladereihenfolge, ohne KI."}

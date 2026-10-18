"""Test model for vehicle drafts (no API key needed): German text rules and the local A4 scale.

It recognises typical van models, stated dimensions ("Laderaum 3,30 x 1,78 x 1,94 m", "1,80 m
hoch"), payload, plate, licence, seats, towing, costs and shelves, and returns honest confidences:
stated values 0.9, model defaults 0.5, values from the photo scale about 0.45, guesses 0.2.
"""

from __future__ import annotations

import re
from typing import Any

from app.fleet.fields import COST_FIELDS, RANGES, REQUIRED, SHELF_FIELDS, VEHICLE_FIELDS

STATED, MODEL, SCALE, GUESS = 0.9, 0.5, 0.45, 0.2

# typical values of common builds (cm, kg); the owner should check them
MODELS: list[tuple[str, dict[str, Any]]] = [
    (
        r"sprinter",
        {
            "name": "Sprinter",
            "kind": "van",
            "cargo_length_cm": 330,
            "cargo_width_cm": 178,
            "cargo_height_cm": 194,
            "door_width_cm": 156,
            "door_height_cm": 184,
            "payload_kg": 1200,
            "required_licence": "B",
            "seats": 3,
            "wheel_arch_x_cm": 165,
            "wheel_arch_length_cm": 95,
            "wheel_arch_width_cm": 21,
            "wheel_arch_height_cm": 30,
        },
    ),
    (
        r"crafter",
        {
            "name": "Crafter",
            "kind": "van",
            "cargo_length_cm": 345,
            "cargo_width_cm": 183,
            "cargo_height_cm": 196,
            "door_width_cm": 157,
            "door_height_cm": 184,
            "payload_kg": 1150,
            "required_licence": "B",
            "seats": 3,
            "wheel_arch_x_cm": 170,
            "wheel_arch_length_cm": 95,
            "wheel_arch_width_cm": 22,
            "wheel_arch_height_cm": 30,
        },
    ),
    (
        r"transit",
        {
            "name": "Transit",
            "kind": "van",
            "cargo_length_cm": 330,
            "cargo_width_cm": 178,
            "cargo_height_cm": 188,
            "door_width_cm": 157,
            "door_height_cm": 181,
            "payload_kg": 1150,
            "required_licence": "B",
            "seats": 3,
        },
    ),
    (
        r"ducato|boxer|jumper",
        {
            "name": "Ducato",
            "kind": "van",
            "cargo_length_cm": 370,
            "cargo_width_cm": 187,
            "cargo_height_cm": 193,
            "door_width_cm": 156,
            "door_height_cm": 188,
            "payload_kg": 1400,
            "required_licence": "B",
            "seats": 3,
        },
    ),
    (
        r"vito|vivaro|trafic|transporter t\d|\bt6\b|\bt7\b|bulli",
        {
            "name": "Kleintransporter",
            "kind": "van",
            "cargo_length_cm": 255,
            "cargo_width_cm": 170,
            "cargo_height_cm": 140,
            "door_width_cm": 147,
            "door_height_cm": 130,
            "payload_kg": 900,
            "required_licence": "B",
            "seats": 3,
        },
    ),
    (
        r"7[,.]5\s*-?\s*t|7[,.]5-tonner|ladebordwand|\blkw\b",
        {
            "name": "7,5-Tonner",
            "kind": "truck",
            "cargo_length_cm": 610,
            "cargo_width_cm": 245,
            "cargo_height_cm": 240,
            "door_width_cm": 240,
            "door_height_cm": 230,
            "payload_kg": 2500,
            "required_licence": "C1",
            "seats": 3,
        },
    ),
    (
        r"anhänger|hänger",
        {
            "name": "Anhänger",
            "kind": "trailer",
            "cargo_length_cm": 300,
            "cargo_width_cm": 150,
            "cargo_height_cm": 180,
            "door_width_cm": 145,
            "door_height_cm": 175,
            "payload_kg": 1000,
            "required_licence": "BE",
            "seats": 0,
        },
    ),
]

LABELS = {
    "cargo_length_cm": "Länge des Laderaums (Stirnwand bis Tür)",
    "cargo_width_cm": "Breite des Laderaums",
    "cargo_height_cm": "Höhe des Laderaums",
    "payload_kg": "zulässige Nutzlast laut Fahrzeugschein",
    "door_width_cm": "Breite der Ladetür",
    "door_height_cm": "Höhe der Ladetür",
}


def vf(value: Any, confidence: float) -> dict[str, Any]:
    return {"value": value, "confidence": round(confidence, 2) if value is not None else 0.0}


def _num(s: str) -> float:
    return (
        float(s.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s)
        else float(s.replace(",", "."))
    )


def _cm(value: str, unit: str | None) -> float:
    v = _num(value)
    if unit in ("m", "meter") or (unit is None and v < 10):
        return round(v * 100)
    if unit == "mm":
        return round(v / 10)
    return round(v)


N = r"(\d+(?:[.,]\d+)?)"
U = r"\s*(mm|cm|m|meter)?"


def parse_text(
    text: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict] | None, bool]:
    """Values stated in a German text: (vehicle, costs, shelves or None = unchanged, shelves removed)."""
    low = " " + text.lower().replace("\n", " ") + " "
    v: dict[str, dict[str, Any]] = {}
    c: dict[str, dict[str, Any]] = {}
    # known model first, explicit numbers win afterwards
    for pattern, values in MODELS:
        if re.search(pattern, low):
            for k, val in values.items():
                v[k] = vf(val, MODEL)
            break
    m = re.search(N + U + r"\s*[x×*]\s*" + N + U + r"\s*[x×*]\s*" + N + U, low)
    if m:
        unit = m.group(6) or m.group(4) or m.group(2)
        v["cargo_length_cm"] = vf(_cm(m.group(1), m.group(2) or unit), STATED)
        v["cargo_width_cm"] = vf(_cm(m.group(3), m.group(4) or unit), STATED)
        v["cargo_height_cm"] = vf(_cm(m.group(5), m.group(6) or unit), STATED)
    for sentence in re.split(r"[.;!?\n]", low):
        if not sentence.strip():
            continue
        door = "tür" in sentence or "öffnung" in sentence
        if "regal" in sentence or "radk" in sentence:
            continue  # parsed below
        for word, key, door_key in (
            ("lang", "cargo_length_cm", None),
            ("breit", "cargo_width_cm", "door_width_cm"),
            ("hoch", "cargo_height_cm", "door_height_cm"),
        ):
            mm = re.search(N + U + r"\s*(?:\w+\s){0,1}" + word, sentence) or re.search(
                word + r"\w*\s*(?:ist|von|mit|:)?\s*(?:ca\.?|etwa|ungefähr)?\s*" + N + U, sentence
            )
            if mm:
                target = door_key if door and door_key else key
                if target:
                    v[target] = vf(_cm(mm.group(1), mm.group(2)), STATED)
    m = re.search(r"(?:nutzlast|zuladung)\D{0,25}" + N + r"\s*(kg|t|tonnen)?", low) or re.search(
        N + r"\s*(kg|t)\s*(?:nutzlast|zuladung)", low
    )
    if m:
        val = _num(m.group(1))
        v["payload_kg"] = vf(
            round(val * 1000 if (m.group(2) in ("t", "tonnen") or val < 20) else val), STATED
        )
    m = re.search(r"\b([a-zäöü]{1,3}-[a-z]{1,2}\s?\d{1,4}[eh]?)\b", low)
    if m:
        v["plate"] = vf(m.group(1).upper(), STATED)
    m = re.search(r"(?:führerschein|klasse)\s*(?:klasse\s*)?(c1e|ce|c1|be|b|c)\b", low)
    if m:
        v["required_licence"] = vf(m.group(1).upper(), STATED)
    elif re.search(r"3[,.]5\s*-?\s*t", low) and "required_licence" not in v:
        v["required_licence"] = vf("B", 0.8)
    m = re.search(r"(\d)\s*(?:sitze|sitzplätze|plätze vorne|personen vorne)", low)
    if m:
        v["seats"] = vf(int(m.group(1)), STATED)
    if re.search(r"anhängerkupplung|ahk\b", low):
        v["can_tow"] = vf(True, STATED)
        m = re.search(r"(?:anhängelast|zieht|bis)\D{0,10}" + N + r"\s*(kg|t)", low)
        if m:
            val = _num(m.group(1))
            v["max_trailer_kg"] = vf(round(val * 1000 if m.group(2) == "t" else val), STATED)
    m = re.search(
        r"(?:heißt|name(?:\s*ist)?\s*:?)\s+[„\"']?([\wäöüß][\wäöüß \-]{1,40}?)[\"“']?(?=[,.;]|$| mit| und)",
        text,
        re.I,
    )
    if m:
        v["name"] = vf(m.group(1).strip(), STATED)
    m = re.search(N + r"\s*(?:€|euro)\s*(?:pro|je|/)\s*km", low)
    if m:
        c["cost_per_km"] = vf(_num(m.group(1)), STATED)
    m = re.search(N + r"\s*(?:€|euro)\s*(?:pro|je|/)\s*(?:stunde|std|h)\b", low)
    if m:
        c["cost_per_hour"] = vf(_num(m.group(1)), STATED)
    m = re.search(N + r"\s*(?:l|liter)\s*(?:auf|pro|je|/)\s*100", low)
    if m:
        c["fuel_l_per_100km"] = vf(_num(m.group(1)), STATED)
    # shelves and wheel arches
    removed = bool(
        re.search(
            r"(?:kein|ohne|entfern\w*|ausgebaut)\D{0,20}regal|regal\D{0,20}(?:entfern|ausgebaut|raus)", low
        )
    )
    shelves: list[dict] | None = None
    for sentence in re.split(r"[.;!?\n]", low):
        if "radk" in sentence:
            for word, key in (
                ("lang", "wheel_arch_length_cm"),
                ("breit", "wheel_arch_width_cm"),
                ("hoch", "wheel_arch_height_cm"),
            ):
                mm = re.search(N + U + r"\s*" + word, sentence)
                if mm:
                    v[key] = vf(_cm(mm.group(1), mm.group(2) or "cm"), STATED)
            mm = re.search(r"ab\s*" + N + U, sentence)
            if mm:
                v["wheel_arch_x_cm"] = vf(_cm(mm.group(1), mm.group(2) or "cm"), STATED)
        if "regal" in sentence and not removed:
            dims = {}
            for word, key in (
                ("lang", "length_cm"),
                ("tief", "depth_cm"),
                ("hoch", "clearance_cm"),
                ("höhe", "height_cm"),
            ):
                mm = re.search(N + U + r"\s*" + word, sentence) or re.search(
                    word + r"\w*\s*(?:von)?\s*" + N + U, sentence
                )
                if mm:
                    dims[key] = _cm(mm.group(1), mm.group(2) or "cm")
            mm = re.search(r"in\s*" + N + U + r"\s*höhe", sentence)
            if mm:
                dims["height_cm"] = _cm(mm.group(1), mm.group(2) or "cm")
            mm = re.search(N + r"\s*kg", sentence)
            if not dims:
                continue
            side = "rechts" if "rechts" in sentence else "links"
            shelf = {
                "name": vf(f"Regal {side}", STATED),
                "x_cm": vf(0, 0.5),
                "y_cm": vf(0 if side == "links" else None, 0.6),
                "length_cm": vf(dims.get("length_cm", 120), STATED if "length_cm" in dims else GUESS),
                "depth_cm": vf(dims.get("depth_cm", 40), STATED if "depth_cm" in dims else GUESS),
                "height_cm": vf(dims.get("height_cm", 90), STATED if "height_cm" in dims else GUESS),
                "clearance_cm": vf(dims.get("clearance_cm", 60), STATED if "clearance_cm" in dims else GUESS),
                "max_load_kg": vf(_num(mm.group(1)) if mm else 60, STATED if mm else GUESS),
                "_side": side,
            }
            shelves = (shelves or []) + [shelf]
    return v, c, shelves, removed


def _merge(current: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    out = dict(current)
    for k, val in new.items():
        old = out.get(k) or {"value": None, "confidence": 0}
        if val.get("value") is not None and (
            old.get("value") is None
            or val["confidence"] >= old.get("confidence", 0)
            or val["confidence"] >= STATED
        ):
            out[k] = val
    return out


def _plausible(v: dict[str, Any]) -> None:
    for k, (lo, hi) in RANGES.items():
        node = v.get(k)
        if node and node.get("value") is not None and not (lo <= float(node["value"]) <= hi):
            node["confidence"] = min(node["confidence"], 0.2)


def _finish(v, c, shelves, threshold: float, scale: str, intro: str) -> dict[str, Any]:
    for k, _ in VEHICLE_FIELDS:
        v.setdefault(k, vf(None, 0))
    for k, _, _ in COST_FIELDS:
        c.setdefault(k, vf(None, 0))
    width = (v.get("cargo_width_cm") or {}).get("value")
    out_shelves = []
    for s in shelves or []:
        s = dict(s)
        s.pop("_side", None)  # only used while parsing
        if (s.get("y_cm") or {}).get("value") is None:
            depth = (s.get("depth_cm") or {}).get("value") or 40
            s["y_cm"] = vf(width - depth if width else None, 0.5)  # right wall
        for k, _ in SHELF_FIELDS:
            s.setdefault(k, vf(None, 0))
        out_shelves.append(s)
    _plausible(v)
    questions = []
    for k in REQUIRED:
        node = v.get(k) or {}
        if node.get("value") is None:
            questions.append(
                f"Wie groß ist die {LABELS[k]}?"
                if k != "payload_kg"
                else "Wie hoch ist die zulässige Nutzlast laut Fahrzeugschein?"
            )
        elif node.get("confidence", 0) < threshold:
            questions.append(
                f"Bitte prüfen: {LABELS[k]} – geschätzt {node['value']:g} {'kg' if k == 'payload_kg' else 'cm'}. Stimmt das?"
            )
    known = [
        f"{LABELS[k].split(' (')[0]} {v[k]['value']:g} {'kg' if k == 'payload_kg' else 'cm'}"
        for k in REQUIRED
        if (v.get(k) or {}).get("value") is not None
    ]
    reply = intro + (" Eingetragen: " + "; ".join(known) + "." if known else "")
    if questions:
        reply += " Offen sind noch einige Angaben, siehe Rückfragen."
    return {
        "vehicle": v,
        "costs": c,
        "shelves": out_shelves,
        "scale": scale,
        "questions": questions[:3],
        "reply": reply,
    }


def fake_vehicle_chat(context: dict[str, Any]) -> dict[str, Any]:
    current = context.get("draft") or {}
    threshold = float(context.get("threshold", 0.6))
    v = dict(current.get("vehicle") or {})
    c = dict(current.get("costs") or {})
    shelves = current.get("shelves")
    text = " ".join(m.get("text", "") for m in context.get("messages", []) if m.get("role") == "user")
    pv, pc, ps, removed = parse_text(context.get("message") or "")
    if not v:  # first message: also everything said before
        pv, pc, ps, removed = parse_text(text)
    v, c = _merge(v, pv), _merge(c, pc)
    if removed:
        shelves = []
    elif ps is not None:
        shelves = ps
    scale = (
        "stated"
        if any(x.get("confidence", 0) >= STATED for x in pv.values())
        else ("known_model" if pv else "none")
    )
    return _finish(
        v, c, shelves, threshold, scale, "Testmodell ohne KI: Angaben aus Ihrer Nachricht übernommen."
    )


def fake_vehicle_photo(context: dict[str, Any]) -> dict[str, Any]:
    """Cargo-space photo seen from the rear door: width and height from the A4 scale; length is not
    visible from the door and is only guessed."""
    threshold = float(context.get("threshold", 0.6))
    v: dict[str, Any] = {}
    scale = "none"
    for p in context.get("photos", []):
        a4 = p.get("a4") or {}
        if a4.get("detected") and a4.get("cm_per_px") and p.get("width") and p.get("height"):
            cpp = float(a4["cm_per_px"])
            w = round(max(120, min(250, p["width"] * cpp * 0.8)))
            h = round(max(120, min(260, p["height"] * cpp * 0.75)))
            v["cargo_width_cm"] = vf(w, SCALE)
            v["cargo_height_cm"] = vf(h, SCALE)
            v["door_width_cm"] = vf(round(w * 0.88), SCALE - 0.1)
            v["door_height_cm"] = vf(round(h * 0.94), SCALE - 0.1)
            v["cargo_length_cm"] = vf(round(w * 1.9), GUESS)
            v["wheel_arch_width_cm"] = vf(round(w * 0.12), GUESS)
            v["wheel_arch_height_cm"] = vf(30, GUESS)
            scale = "a4"
            break
    if scale == "none":
        for k, val in (
            ("cargo_length_cm", 330),
            ("cargo_width_cm", 178),
            ("cargo_height_cm", 185),
            ("door_width_cm", 155),
            ("door_height_cm", 175),
        ):
            v[k] = vf(val, GUESS)
    v.setdefault("kind", vf("van", 0.5))
    # a note with the photo ("Nutzlast 1200 kg") counts as stated
    pv, pc, ps, _ = parse_text(context.get("note") or "")
    v = _merge(v, pv)
    intro = (
        "Testmodell ohne KI: Breite und Höhe aus dem A4-Maßstab geschätzt, die Länge ist von der Tür aus nur grob zu sehen."
        if scale == "a4"
        else "Testmodell ohne KI: Kein Maßstab erkannt – bitte ein A4-Blatt oder einen Zollstock ins Bild legen."
    )
    return _finish(v, dict(pc), ps or [], threshold, scale, intro)

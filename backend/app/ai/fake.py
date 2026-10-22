"""Fake AI provider: no network call, deterministic rule-based results.

Used for tests, demos and when no AI key is configured. It understands common German phrasings
in customer messages well enough to produce useful drafts with honest confidence values.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

from app.ai.providers import AIRequest, AIResponse, ChatTurn

# species properties the AI returns per plant (see app/timemodel/knowledge.AI_TRAITS)
TRAIT_KEYS = ("compressibility", "tip_tendency", "can_tilt", "frost_sensitive", "sensitive")

NUMBER_WORDS = {
    "ein": 1,
    "eine": 1,
    "einen": 1,
    "einem": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "elf": 11,
    "zwölf": 12,
    "paar": 2,
}
MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
GENERIC_PLANTS = ["kübelpflanze", "pflanze", "palme", "bäumchen", "baum", "strauch", "busch"]


def v(value: Any, confidence: float) -> dict[str, Any]:
    return {"value": value, "confidence": round(confidence, 2) if value is not None else 0.0}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _len_cm(value: str, unit: str) -> float:
    n = _num(value)
    return round(n * 100 if unit.lower() in ("m", "meter") else n, 1)


def _sentences(text: str) -> list[str]:
    """Split into sentences at . ! ? followed by a capital letter, and at blank lines.
    Single line breaks inside a paragraph are treated as spaces."""
    paragraphs = re.split(r"\n\s*\n", text)
    out: list[str] = []
    for para in paragraphs:
        para = re.sub(r"\s*\n\s*", " ", para.strip())
        for part in re.split(r"(?<=[!?])\s+|(?<=[a-zäöüß\)])\.\s+(?=[A-ZÄÖÜ])", para):
            if part.strip():
                out.append(part.strip())
    return out


def _vehicle_fake(kind: str, request: AIRequest) -> dict[str, Any]:
    from app.fleet.fake import fake_vehicle_chat, fake_vehicle_photo

    return fake_vehicle_photo(request.context) if kind == "photo" else fake_vehicle_chat(request.context)


def _team_fake(request: AIRequest) -> dict[str, Any]:
    from app.teams.spontaneous import fake_team_parse

    return fake_team_parse(request.context)


def _formula_fake(request: AIRequest) -> dict[str, Any]:
    from app.formula.debate import fake_turn

    return fake_turn(request.context)


def _layout_fake(request: AIRequest) -> dict[str, Any]:
    from app.packing.ai_layout import fake_layout

    return fake_layout(request.context)


class FakeProvider:
    def complete(
        self, model_name: str, request: AIRequest, api_key: str | None, options: dict[str, Any]
    ) -> AIResponse:
        started = time.monotonic()
        fn = {
            "message_intake": self._intake,
            "completeness_check": self._completeness,
            "photo_analysis": self._photo_analysis,
            "vehicle_photo": lambda r: _vehicle_fake("photo", r),
            "vehicle_chat": lambda r: _vehicle_fake("chat", r),
            "load_layout": _layout_fake,
            "photo_sort": self._photo_sort,
            "follow_up": self._follow_up,
            "team_parse": _team_fake,
            "formula_debate": _formula_fake,
        }.get(request.function)
        data = fn(request) if fn else {"text": "Testmodell: keine Auswertung für diese Funktion."}
        import json

        text = json.dumps(data, ensure_ascii=False)
        return AIResponse(
            text=text,
            data=data,
            input_tokens=len(request.text) // 4 + 200 * len(request.images),
            output_tokens=len(text) // 4,
            model=model_name,
            stop_reason="end_turn",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def generate_image(
        self, model_name: str, prompt: str, api_key: str | None, options: dict[str, Any]
    ) -> bytes:
        from app.ai.images import render_plant

        return render_plant(options["info"])

    def transcribe(
        self, model_name: str, audio: bytes, filename: str, api_key: str | None, options: dict[str, Any]
    ) -> str:
        """The test model cannot listen; the browser's speech recognition is used instead."""
        from app.ai.providers import ProviderError

        raise ProviderError("the test model has no speech recognition")

    # ------------------------------------------------------------------------- intake

    def _intake(self, request: AIRequest) -> dict[str, Any]:
        ctx = request.context
        text = ctx.get("message", request.text)
        low = text.lower()
        species_names: list[str] = ctx.get("species_names", [])
        today = date.fromisoformat(ctx["today"]) if ctx.get("today") else date.today()

        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        phone = re.search(r"(?:\+49|\b0)[\d\s/\-]{6,}\d", text)
        name, name_conf = self._name(text)
        company = re.search(r"\b([A-ZÄÖÜ][\wäöüß&\- ]+ (?:GmbH|AG|KG|e\.\s?K\.|UG|GbR))", text)

        street = re.search(
            r"([A-ZÄÖÜ][\wäöüß\.\-]*(?:[ \-][A-ZÄÖÜa-zäöüß][\wäöüß\.\-]*)*?(?:straße|strasse|str\.|weg|gasse|platz|allee|ring|steige|hof|berg|ufer|damm|pfad|zeile|anlage)\s+\d+\s?[a-zA-Z]?)",
            text,
        )
        plz = re.search(
            r"\b(\d{5})\s+([A-ZÄÖÜ][\wäöüß]+(?:[ \-](?:am|an der|im|bei|ob der|[A-ZÄÖÜ][\wäöüß]+))*)", text
        )
        floor = self._floor(low)
        parking = re.search(r"([^.\n]*(?:park|einfahrt|halteverbot|stellplatz)[^.\n]*)", text, re.I)

        earliest, latest, date_conf = self._dates(low, today)
        plants = self._plants(text, species_names)
        self._traits(plants, ctx.get("species_traits") or {}, low)
        path = self._path(low, floor)

        missing: list[str] = []
        if not street or not plz:
            missing.append("vollständige Adresse")
        if not plants:
            missing.append("Pflanzen")
        elif any(p["total_height_cm"]["value"] is None for p in plants):
            missing.append("Größe der Pflanzen")
        if any(p["pot_diameter_cm"]["value"] is None for p in plants):
            missing.append("Topfgröße")
        if path["length_m"]["value"] is None:
            missing.append("ungefähre Weglänge vom Stellplatz zum Fahrzeug")
        if not ctx.get("photo_count"):
            missing.append("Fotos der Pflanzen (mit A4-Blatt) und des Wegs")
        if earliest is None and latest is None:
            missing.append("Wunschtermin")

        follow_up = ""
        if missing:
            greeting = f"Guten Tag {name}," if name else "Guten Tag,"
            follow_up = (
                f"{greeting}\n\nvielen Dank für Ihre Anfrage zur Überwinterung. Damit wir die Abholung gut planen "
                f"können, fehlen uns noch folgende Angaben: {', '.join(missing)}.\n"
                + (
                    "Bitte fotografieren Sie jede Pflanze von vorn und von der Seite mit einem A4-Blatt am Stamm, "
                    "den Topf aus der Nähe und den Weg vom Standort bis zur Straße (jede Tür und Treppe).\n"
                    if any("Fotos" in m for m in missing)
                    else ""
                )
                + "\nVielen Dank und freundliche Grüße"
            )

        return {
            "customer": {
                "name": v(name, name_conf),
                "company": v(company.group(1).strip() if company else None, 0.8),
                "email": v(email.group(0) if email else None, 0.97),
                "phone": v(re.sub(r"\s+", " ", phone.group(0)).strip() if phone else None, 0.9),
            },
            "address": {
                "street": v(street.group(1).strip() if street else None, 0.85),
                "postal_code": v(plz.group(1) if plz else None, 0.95),
                "city": v(plz.group(2).strip() if plz else None, 0.85),
                "floor": v(floor[0] if floor else None, 0.8),
                "parking_notes": v(parking.group(1).strip() if parking else None, 0.6),
                "access_notes": v(None, 0),
            },
            "order": {
                "earliest_date": v(earliest, date_conf),
                "latest_date": v(latest, date_conf),
                "notes": v(None, 0),
            },
            "plants": plants,
            "path": path,
            "missing": missing,
            "follow_up_message": follow_up,
        }

    @staticmethod
    def _name(text: str) -> tuple[str | None, float]:
        m = re.search(
            r"(?i:mein name ist|ich bin|ich heiße|hier ist)\s+([A-ZÄÖÜ][\wäöüß\-]+(?:[ \t]+[A-ZÄÖÜ][\wäöüß\-]+){0,2})",
            text,
        )
        if m:
            return m.group(1).strip(), 0.9
        m = re.search(
            r"(?i:viele grüße|freundliche grüße|mit freundlichen grüßen|beste grüße|liebe grüße|gruß|lg|vg|mfg)[,!\s]*\n?\s*"
            r"((?:Familie[ \t]+)?[A-ZÄÖÜ][\wäöüß\-]+(?:[ \t]+[A-ZÄÖÜ][\wäöüß\-]+){0,2})",
            text,
        )
        if m:
            return m.group(1).strip(), 0.75
        m = re.search(r"\bFamilie\s+([A-ZÄÖÜ][\wäöüß\-]+)", text)
        if m:
            return f"Familie {m.group(1)}", 0.6
        return None, 0.0

    @staticmethod
    def _floor(low: str) -> tuple[str, int] | None:
        m = re.search(r"(\d+)\.\s*(?:stock|og|etage|obergeschoss)", low)
        if m:
            return f"{m.group(1)}. OG", int(m.group(1))
        if "dachterrasse" in low:
            m2 = re.search(r"(\d+)\s*(?:stockwerke|etagen)", low)
            n = int(m2.group(1)) if m2 else 3
            return "Dachterrasse", n
        if "keller" in low:
            return "Keller", -1
        if "erdgeschoss" in low or "eg " in low:
            return "EG", 0
        return None

    @staticmethod
    def _dates(low: str, today: date) -> tuple[str | None, str | None, float]:
        year = today.year

        def mk(day: int, month: int, y: int | None = None) -> str | None:
            try:
                d = date(y or year, month, day)
            except ValueError:
                return None
            # dates far in the past mean next year; recent ones mean "as soon as possible" this season
            if y is None and (today - d).days > 60:
                d = date(year + 1, month, day)
            return d.isoformat()

        m = re.search(
            r"zwischen (?:dem )?(\d{1,2})\.(?:(\d{1,2})\.)?\s*(?:und|bis)\s*(?:zum )?(\d{1,2})\.(\d{1,2})\.?",
            low,
        )
        if m:
            m1 = int(m.group(2) or m.group(4))
            return mk(int(m.group(1)), m1), mk(int(m.group(3)), int(m.group(4))), 0.85
        m = re.search(
            r"zwischen (?:dem )?(\d{1,2})\.\s*(?:und|bis)\s*(\d{1,2})\.\s*(" + "|".join(MONTHS) + ")", low
        )
        if m:
            mo = MONTHS[m.group(3)]
            return mk(int(m.group(1)), mo), mk(int(m.group(2)), mo), 0.85
        m = re.search(r"\bab (?:dem )?(\d{1,2})\.(\d{1,2})\.(\d{4})?", low)
        if m:
            return mk(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None), None, 0.8
        m = re.search(r"\bbis (?:zum |spätestens )?(\d{1,2})\.(\d{1,2})\.(\d{4})?", low)
        if m:
            return None, mk(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None), 0.8
        m = re.search(r"(anfang|mitte|ende) (" + "|".join(MONTHS) + ")", low)
        if m:
            mo = MONTHS[m.group(2)]
            start, end = {"anfang": (1, 10), "mitte": (10, 20), "ende": (20, 28)}[m.group(1)]
            return mk(start, mo), mk(end, mo), 0.6
        return None, None, 0.0

    @staticmethod
    def _traits(plants: list[dict[str, Any]], known: dict[str, dict[str, Any]], low: str) -> None:
        """Species properties: from the catalog (moderate confidence) or stated in the message."""
        frost_said = re.search(r"frostempfindlich|verträgt(?: \w+)? keinen frost|nicht winterhart", low)
        for p in plants:
            name = (p.get("species") or {}).get("value")
            traits = known.get(name) if name else None
            for key in TRAIT_KEYS:
                p[key] = v(traits[key], 0.55) if traits and traits.get(key) is not None else v(None, 0)
            if frost_said:
                p["frost_sensitive"] = v(True, 0.9)

    def _plants(self, text: str, species_names: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        generic = set(GENERIC_PLANTS) | {g + "n" for g in GENERIC_PLANTS}
        names = sorted(
            {n for n in species_names if n and n.lower() not in generic and "(" not in n},
            key=len,
            reverse=True,
        )
        count_words = "|".join(NUMBER_WORDS)
        for sentence in _sentences(text):
            low = sentence.lower()
            found: list[tuple[int, int, str | None, float]] = []
            for name in names:
                stem = name.lower()
                pattern = r"\b" + re.escape(stem[: max(4, len(stem) - 1)]) + r"\w*"
                for m in re.finditer(pattern, low):
                    if any(a <= m.start() < b or m.start() <= a < m.end() for a, b, _, _ in found):
                        continue
                    found.append((m.start(), m.end(), name, 0.85))
            if not found:
                for g in GENERIC_PLANTS:
                    for m in re.finditer(r"\b" + g + r"\w*", low):
                        before = low[max(0, m.start() - 25) : m.start()]
                        after = low[m.end() : m.end() + 60]
                        counted = re.search(r"(\d+|" + count_words + r")\s+(?:\w+\s+)?$", before)
                        sized = re.search(
                            r"\d+(?:[,.]\d+)?\s*(?:m|cm)\b\s*(?:hoch|groß)|(?:topf|kübel)\s*\d", after
                        )
                        if counted or sized:
                            found.append((m.start(), m.end(), None, 0.4))
                            break
                    if found:
                        break
            found.sort()
            for idx, (start, end, name, conf) in enumerate(found):
                stop = found[idx + 1][0] if idx + 1 < len(found) else len(low)
                window = low[end:stop]
                before = low[max(0, start - 30) : start]
                count, count_conf = 1, 0.5
                cm = re.search(r"(\d+|" + count_words + r")\s+(?:\w+\s+){0,2}$", before)
                if cm:
                    word = cm.group(1)
                    count = int(word) if word.isdigit() else NUMBER_WORDS.get(word, 1)
                    count_conf = 0.9
                pot = re.search(
                    r"(?:topf|töpf|kübel|gefäß)[^,.;]{0,30}?(\d+(?:[,.]\d+)?)\s*(cm|m)\b", window
                ) or re.search(
                    r"(\d+(?:[,.]\d+)?)\s*(cm|m)\s*(?:großen|großem|breiten|durchmesser)?\s*(?:topf|töpf|kübel)",
                    window,
                )
                height = re.search(
                    r"(\d+(?:[,.]\d+)?)\s*(m|cm|meter)\b\s*(?:\w+\s*){0,1}(?:hoch|groß|höhe)", window
                ) or re.search(
                    r"(?:höhe|hoch|groß)\s*(?:von|ca\.?|etwa|ungefähr)?\s*(\d+(?:[,.]\d+)?)\s*(m|cm|meter)",
                    window,
                )
                width = re.search(
                    r"(?:krone|breit)[^,.;]{0,20}?(\d+(?:[,.]\d+)?)\s*(m|cm)\b|(\d+(?:[,.]\d+)?)\s*(m|cm)\s*(?:breit|ausladend)",
                    window,
                )
                weight = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:kg|kilo)", window)
                lm = re.search(
                    r"(links|rechts|vorne|hinten|auf der terrasse|auf dem balkon|im garten|im wintergarten)",
                    window,
                )
                label = lm.group(1) if lm else None
                h_cm = _len_cm(height.group(1), height.group(2)) if height else None
                p_cm = _len_cm(pot.group(1), pot.group(2)) if pot else None
                w_cm = None
                if width:
                    w_cm = (
                        _len_cm(width.group(1), width.group(2))
                        if width.group(1)
                        else _len_cm(width.group(3), width.group(4))
                    )
                if p_cm is not None and h_cm is not None and abs(p_cm - h_cm) < 1:
                    p_cm = None
                out.append(
                    {
                        "label": v((name or "Pflanze") + (f" ({label})" if label else ""), 0.7),
                        "species": v(name, conf if name else 0.0),
                        "count": v(count, count_conf),
                        "pot_diameter_cm": v(p_cm, 0.75),
                        "pot_height_cm": v(None, 0),
                        "total_height_cm": v(h_cm, 0.8),
                        "crown_width_cm": v(w_cm, 0.7),
                        "weight_kg": v(_num(weight.group(1)) if weight else None, 0.6),
                        "location": v(label, 0.6),
                        "notes": v(None, 0),
                    }
                )
        return out

    @staticmethod
    def _path(low: str, floor: tuple[str, int] | None) -> dict[str, Any]:
        low = re.sub(r"\b(ca|ungef|bzw|evtl|max|min)\.", r"\1", low)
        steps = re.search(r"(\d+)\s*(?:stufen|treppenstufen)", low)
        length = re.search(
            r"(\d+(?:[,.]\d+)?)\s*(?:m|meter)\b[^.]{0,30}(?:weg|weit|entfernt|bis|zur straße|zum auto|zum tor)",
            low,
        ) or re.search(
            r"(?:weg|entfernung|abstand|straße|auto|tor|parkplatz|einfahrt)[^.]{0,30}?(\d+(?:[,.]\d+)?)\s*(?:m|meter)\b",
            low,
        )
        width = re.search(
            r"(\d+)\s*cm\s*(?:breit|breite)[^.]{0,20}|(?:tür|durchgang|gang|tor|engstelle)[^.]{0,30}?(\d+)\s*cm",
            low,
        )
        elevator = None
        if re.search(r"(kein|ohne)\w*\s+(aufzug|fahrstuhl|lift)", low) or re.search(
            r"(aufzug|fahrstuhl|lift)\w*\s+(?:gibt es\s+|haben wir\s+|ist\s+)?(?:leider\s+)?(?:kein|nicht)",
            low,
        ):
            elevator = False
        elif re.search(r"aufzug|fahrstuhl|\blift\b", low):
            elevator = True
        n_steps = int(steps.group(1)) if steps else None
        steps_conf = 0.9 if steps else 0.0
        height = None
        if n_steps is None and floor and floor[1] > 0 and not elevator:
            n_steps = floor[1] * 18
            steps_conf = 0.4
        if floor and floor[1] != 0:
            height = abs(floor[1]) * 2.9
        elif n_steps:
            height = round(n_steps * 0.17, 2)
        surface = None
        for word, s in (
            ("kies", "gravel"),
            ("rasen", "lawn"),
            ("pflaster", "paved"),
            ("fliesen", "tiles"),
            ("holz", "wood"),
            ("wiese", "lawn"),
        ):
            if word in low:
                surface = s
                break
        desc_bits = []
        if floor:
            desc_bits.append(floor[0])
        if "treppe" in low:
            desc_bits.append("Treppe")
        if elevator:
            desc_bits.append("Aufzug")
        w = None
        if width:
            w = float(width.group(1) or width.group(2))
        return {
            "length_m": v(_num(length.group(1)) if length else None, 0.65),
            "steps": v(n_steps, steps_conf),
            "height_m": v(round(height, 2) if height is not None else None, 0.5),
            "min_width_cm": v(w, 0.7),
            "elevator": v(elevator, 0.85),
            "surface": v(surface, 0.6),
            "description": v(", ".join(desc_bits) or None, 0.6),
        }

    # ------------------------------------------------------------------------- photos

    def _photo_sort(self, request: AIRequest) -> dict[str, Any]:
        """Portrait photos or photos with an A4 sheet show plants (front, side, top, pot in turn, spread
        evenly over the plants of the message); landscape photos without A4 sheet show the path."""
        photos = request.context.get("photos", [])
        n_plants = max(1, len(request.context.get("plants") or []))
        plant_idx, path_idx = [], []
        for i, p in enumerate(photos):
            landscape = (p.get("width") or 0) > (p.get("height") or 0) * 1.15
            a4 = bool((p.get("a4") or {}).get("detected"))
            (path_idx if landscape and not a4 else plant_idx).append(i)
        per = max(1, -(-len(plant_idx) // n_plants))
        kinds = ["plant_front", "plant_side", "plant_top", "pot"]
        out = []
        for k, i in enumerate(plant_idx):
            out.append(
                {
                    "index": i + 1,
                    "kind": kinds[(k % per) % len(kinds)],
                    "plant": min(n_plants, k // per + 1),
                    "confidence": 0.4,
                    "description": "Testmodell: Pflanzenfoto (Hochformat oder A4-Blatt)",
                }
            )
        for k, i in enumerate(path_idx):
            kind = "path_start" if k == 0 else "path_end" if k == len(path_idx) - 1 else "path_segment"
            out.append(
                {
                    "index": i + 1,
                    "kind": kind,
                    "plant": None,
                    "confidence": 0.4,
                    "description": "Testmodell: Querformat ohne A4-Blatt, vermutlich Weg",
                }
            )
        out.sort(key=lambda x: x["index"])
        return {
            "photos": out,
            "plants_seen": min(n_plants, len(plant_idx)),
            "notes": "Testmodell ohne KI: Zuordnung nach Bildformat und Reihenfolge.",
        }

    def _follow_up(self, request: AIRequest) -> dict[str, Any]:
        ctx = request.context
        name = ctx.get("customer")
        lines = [f"Guten Tag {name}," if name else "Guten Tag,", ""]
        lines.append(
            "vielen Dank für Ihre Anfrage zur Überwinterung Ihrer Kübelpflanzen. Damit wir die Abholung gut "
            "planen können, fehlt uns noch Folgendes:"
        )
        for m in ctx.get("missing") or []:
            lines.append(f"- {m}")
        for f in ctx.get("feedback") or []:
            lines.append(f"- {f}")
        if ctx.get("feedback"):
            lines += [
                "",
                "Bitte fotografieren Sie jede Pflanze ganz von vorn und von der Seite mit einem A4-Blatt am Stamm "
                "als Maßstab, den Topf aus der Nähe und den Weg vom Stellplatz bis zur Straße (jede Tür und "
                "Treppe).",
            ]
        if ctx.get("link"):
            lines += [
                "",
                "Am einfachsten laden Sie die Fotos über diesen persönlichen Link hoch; dort können Sie auch "
                f"Ihren Standort teilen: {ctx['link']}",
            ]
        lines += ["", "Vielen Dank und freundliche Grüße", ctx.get("tenant") or ""]
        return {
            "subject": "Fotos für die Abholung Ihrer Kübelpflanzen",
            "message": "\n".join(lines).strip(),
        }

    def _completeness(self, request: AIRequest) -> dict[str, Any]:
        photos = request.context.get("photos", [])
        required = request.context.get("required_kinds", [])
        labels = request.context.get("kind_labels", {})
        plant_names = request.context.get("plants") or []
        if any(p.get("plant") for p in photos):
            return self._completeness_per_plant(photos, required, labels, plant_names)
        result_photos = []
        feedback = []
        present = {p["kind"] for p in photos}
        for i, p in enumerate(photos, start=1):
            issues = []
            q = p.get("quality", {})
            if q and not q.get("sharp", True):
                issues.append("unscharf")
            if q and not q.get("exposure_ok", True):
                issues.append("zu dunkel" if q.get("brightness", 0.5) < 0.5 else "zu hell")
            a4 = p.get("a4") or {}
            needs_a4 = p["kind"] in ("plant_front", "plant_side", "pot")
            if needs_a4 and not a4.get("detected"):
                issues.append("A4-Blatt nicht erkannt")
            elif needs_a4 and a4.get("detected") and not a4.get("fully_visible", True):
                issues.append("A4-Blatt nicht vollständig sichtbar")
            for issue in issues:
                feedback.append(f"Bild {i} ({labels.get(p['kind'], p['kind'])}): {issue}")
            result_photos.append(
                {
                    "index": i,
                    "kind": p["kind"],
                    "usable": not any(x in ("unscharf",) for x in issues),
                    "plant_fully_visible": None,
                    "a4_visible": bool(a4.get("detected")) if needs_a4 else None,
                    "issues": issues,
                }
            )
        missing = [labels.get(k, k) for k in required if k not in present]
        for m in missing:
            feedback.append(f"Bild fehlt: {m}")
        path_kinds = [p for p in photos if p["kind"].startswith("path")]
        path_complete = None
        if any(k.startswith("path") for k in required):
            path_complete = {"path_start", "path_end"} <= {p["kind"] for p in path_kinds}
            if not path_complete:
                feedback.append("Weg nicht lückenlos: Start- und Endpunkt fotografieren")
        return {
            "photos": result_photos,
            "missing": missing,
            "path_complete": path_complete,
            "overall_ok": not feedback,
            "feedback": feedback,
        }

    @staticmethod
    def _completeness_per_plant(
        photos: list[dict[str, Any]], required: list[str], labels: dict[str, str], names: list[str]
    ) -> dict[str, Any]:
        """Photos sorted to plants: every plant needs the plant set, the path start and end once."""
        plant_kinds = [k for k in required if not k.startswith("path")]
        path_kinds = [k for k in required if k.startswith("path")]
        by_plant: dict[int, set[str]] = {}
        for p in photos:
            if p.get("plant"):
                by_plant.setdefault(int(p["plant"]), set()).add(p["kind"])
        n = max([len(names), *by_plant.keys()])
        feedback, missing, result_photos = [], [], []
        for i, p in enumerate(photos, start=1):
            issues = []
            q = p.get("quality") or {}
            if q and not q.get("sharp", True):
                issues.append("unscharf")
                feedback.append(f"Bild {i}: unscharf")
            result_photos.append(
                {
                    "index": i,
                    "kind": p["kind"],
                    "usable": not issues,
                    "plant_fully_visible": None,
                    "a4_visible": bool((p.get("a4") or {}).get("detected")),
                    "issues": issues,
                }
            )
        for no in range(1, n + 1):
            have = by_plant.get(no, set())
            name = names[no - 1] if no <= len(names) else f"Pflanze {no}"
            lacking = [labels.get(k, k) for k in plant_kinds if k not in have]
            if lacking:
                missing += [f"Pflanze {no} ({name}): {m}" for m in lacking]
                feedback.append(f"Pflanze {no} ({name}): {', '.join(lacking)}")
        present = {p["kind"] for p in photos}
        path_missing = [labels.get(k, k) for k in path_kinds if k != "path_segment" and k not in present]
        if path_missing:
            missing += path_missing
            feedback.append("Weg: " + ", ".join(path_missing))
        return {
            "photos": result_photos,
            "missing": missing,
            "path_complete": not path_missing if path_kinds else None,
            "overall_ok": not feedback,
            "feedback": feedback,
        }

    def _photo_analysis(self, request: AIRequest) -> dict[str, Any]:
        photos = request.context.get("photos", [])
        height = width = pot = None
        a4_used = False
        for p in photos:
            a4 = p.get("a4") or {}
            if not a4.get("detected") or not a4.get("cm_per_px"):
                continue
            a4_used = True
            if p["kind"] in ("plant_front", "plant_side") and p.get("height") and height is None:
                height = round(p["height"] * 0.8 * a4["cm_per_px"], 0)
                width = round(p.get("width", 0) * 0.5 * a4["cm_per_px"], 0)
            if p["kind"] == "pot" and pot is None and a4.get("bbox"):
                pot = round(a4["bbox"][2] * a4["cm_per_px"] * 2.0, 0)
        nothing = v(None, 0)
        return {
            "plant": {
                "species": nothing,
                "total_height_cm": v(height, 0.35),
                "crown_width_cm": v(width, 0.3),
                "crown_height_cm": nothing,
                "crown_shape": nothing,
                "crown_density": nothing,
                "pot_diameter_cm": v(pot, 0.3),
                "pot_height_cm": nothing,
                "pot_shape": nothing,
                "pot_material": nothing,
                "weight_kg": nothing,
                **{k: nothing for k in TRAIT_KEYS},
            },
            "path": {
                "length_m": nothing,
                "steps": nothing,
                "height_m": nothing,
                "min_width_cm": nothing,
                "doors": nothing,
                "surface": nothing,
                "elevator": nothing,
            },
            "a4_used": a4_used,
            "notes": "Testmodell ohne KI: grobe Schätzung aus dem A4-Maßstab.",
        }

    # ------------------------------------------------------------------------- chat (settings AI)

    def chat(self, model_name, system, messages, tools, api_key, options) -> ChatTurn:
        """Very small intent parser: 'setze X auf Y', 'setze X zurück', 'was bedeutet X'."""
        index: list[dict[str, str]] = options.get("settings_index", [])
        last = messages[-1]
        if (
            last["role"] == "user"
            and isinstance(last["content"], list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in last["content"])
        ):
            results = [
                b.get("content")
                for b in last["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            return ChatTurn(
                text="Erledigt. " + " ".join(str(r) for r in results),
                tool_calls=[],
                raw_content=[],
                stop_reason="end_turn",
            )
        text = (
            last["content"]
            if isinstance(last["content"], str)
            else " ".join(b.get("text", "") for b in last["content"] if isinstance(b, dict))
        )
        low = text.lower()

        def best_key(fragment: str) -> str | None:
            words = [
                w
                for w in re.findall(r"[a-zäöüß]{3,}", fragment.lower())
                if w not in ("setze", "stelle", "bitte", "den", "die", "das", "auf", "wert", "für")
            ]
            best, score = None, 0
            for item in index:
                hay = (item["label"] + " " + item["key"]).lower()
                # whole words count more than word beginnings
                s = sum(3 if w in hay else 1 if w[:5] in hay else 0 for w in words)
                if s > score:
                    best, score = item["key"], s
            return best

        m = re.search(r"(?:setze|stelle|ändere|änder)\s+(.+?)\s+auf\s+([\w,.:\-]+)", low)
        if m:
            key = best_key(m.group(1))
            if key:
                value: Any = m.group(2).rstrip(".")
                value = value.replace(",", ".")
                try:
                    value = float(value) if "." in value else int(value)
                except ValueError:
                    value = {"ja": True, "an": True, "nein": False, "aus": False}.get(value, value)
                scope = (
                    "tenant"
                    if "betrieb" in low or options.get("default_scope") == "tenant"
                    else options.get("default_scope", "tenant")
                )
                return ChatTurn(
                    text="",
                    tool_calls=[
                        {
                            "id": "fake-1",
                            "name": "set_setting",
                            "input": {"key": key, "value": value, "scope": scope, "object_id": None},
                        }
                    ],
                    raw_content=[],
                    stop_reason="tool_use",
                )
        m = re.search(r"(?:setze|stelle)\s+(.+?)\s+zurück", low) or re.search(r"zurücksetzen:?\s+(.+)", low)
        if m:
            key = best_key(m.group(1))
            if key:
                return ChatTurn(
                    text="",
                    tool_calls=[
                        {
                            "id": "fake-2",
                            "name": "reset_setting",
                            "input": {
                                "key": key,
                                "scope": options.get("default_scope", "tenant"),
                                "object_id": None,
                            },
                        }
                    ],
                    raw_content=[],
                    stop_reason="tool_use",
                )
        key = best_key(low)
        if key:
            return ChatTurn(
                text="",
                tool_calls=[{"id": "fake-3", "name": "explain_setting", "input": {"key": key}}],
                raw_content=[],
                stop_reason="tool_use",
            )
        return ChatTurn(
            text="Ich bin das Testmodell ohne KI. Ich verstehe Sätze wie „Setze den Mindestpreis auf 59“ oder „Was bedeutet der Tragefaktor?“.",
            tool_calls=[],
            raw_content=[],
            stop_reason="end_turn",
        )

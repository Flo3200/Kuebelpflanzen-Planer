"""AI function test (round 2, package S): every AI function once with the model set for it.

For the test day with real keys: one click in the admin area runs each function with a small, made-up
example (no customer data) and reports model, duration, cost and errors per function.
"""

from __future__ import annotations

import io
import time
from datetime import date
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.ai import service as ai
from app.ai.providers import AIImage, ProviderError, get_provider
from app.core.errors import AppError
from app.settings.service import SettingsResolver

MESSAGE = (
    "Guten Tag, wir möchten zwei Oleander (1,60 m hoch, Topf 50 cm) und einen Olivenbaum (2 m, Kübel 70 cm, ca. "
    "90 kg) überwintern lassen. Sie stehen auf der Terrasse, 15 m bis zur Straße, 6 Stufen. Abholung zwischen dem "
    "20. und 31.10. Viele Grüße, Erika Muster, Musterweg 1, 70173 Stuttgart"
)


def _test_photo(a4: bool = True, landscape: bool = False) -> bytes:
    size = (1200, 800) if landscape else (900, 1200)
    img = Image.new("RGB", size, (88, 120, 70))
    d = ImageDraw.Draw(img)
    if not landscape:
        d.rectangle([300, 800, 600, 1150], fill=(160, 90, 60))
        d.ellipse([200, 150, 700, 820], fill=(40, 100, 45))
    if a4:
        d.rectangle([380, 560, 520, 758], fill=(250, 250, 248))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def _cases() -> list[tuple[str, str, dict[str, Any], list[AIImage]]]:
    """(function, text, context for the test model, images)."""
    plant = AIImage(data=_test_photo(), label="Bild 1")
    path = AIImage(data=_test_photo(a4=False, landscape=True), label="Bild 2")
    photos_ctx = [
        {
            "kind": "plant_front",
            "plant": 1,
            "quality": {"sharp": True},
            "a4": {"detected": True, "cm_per_px": 0.21},
            "width": 900,
            "height": 1200,
        },
        {
            "kind": "path_start",
            "plant": None,
            "quality": {"sharp": True},
            "a4": {},
            "width": 1200,
            "height": 800,
        },
    ]
    today = date.today().isoformat()
    return [
        (
            "message_intake",
            f"Heute ist der {today}.\nNachricht:\n{MESSAGE}",
            {"message": MESSAGE, "today": today, "photo_count": 0},
            [],
        ),
        (
            "photo_sort",
            "Pflanzen laut Nachricht:\nPflanze 1: Oleander\nFotos: Bild 1, Bild 2",
            {"photos": photos_ctx, "plants": ["Oleander"]},
            [plant, path],
        ),
        (
            "completeness_check",
            "Erwartete Fotoarten je Pflanze: frontal, seitlich, Topf; Weg Start und Ende.",
            {
                "photos": photos_ctx,
                "required_kinds": ["plant_front", "plant_side", "pot", "path_start", "path_end"],
                "kind_labels": {},
                "plants": ["Oleander"],
            },
            [plant, path],
        ),
        ("photo_analysis", "Fotos: Bild 1 Pflanze frontal mit A4-Blatt", {"photos": photos_ctx[:1]}, [plant]),
        (
            "follow_up",
            "Betrieb: Testgärtnerei\nKunde: Erika Muster\nFehlende Fotos: Pflanze 1: Topf aus der Nähe\nLink: keiner",
            {
                "tenant": "Testgärtnerei",
                "customer": "Erika Muster",
                "plants": ["Oleander"],
                "missing": [],
                "feedback": ["Pflanze 1: Topf aus der Nähe"],
                "link": None,
            },
            [],
        ),
        (
            "team_parse",
            f"Heute ist der {today}.\nPersonal: Lea Roth, Tom Berger\nFahrzeuge: Sprinter\nNachricht: Morgen fahren Lea und Tom mit dem Sprinter",
            {
                "text": "Morgen fahren Lea und Tom mit dem Sprinter",
                "today": today,
                "staff": ["Lea Roth", "Tom Berger"],
                "vehicles": ["Sprinter"],
            },
            [],
        ),
        (
            "vehicle_chat",
            "Neue Nachricht: Mercedes Sprinter, Laderaum 3,30 x 1,78 x 1,94 m, Nutzlast 1.150 kg.",
            {
                "message": "Mercedes Sprinter, Laderaum 3,30 x 1,78 x 1,94 m, Nutzlast 1.150 kg.",
                "messages": [{"role": "user", "text": "Mercedes Sprinter"}],
                "threshold": 0.6,
            },
            [],
        ),
        (
            "formula_debate",
            "Formel time: duration = t_fixed + sum_plants(work) / team. Eröffne die Diskussion.",
            {
                "role": "open",
                "label": "Test",
                "current": {
                    "expressions": [
                        {"name": "work", "level": "plant", "expr": "a0 + a1 * weight"},
                        {"name": "duration", "level": "stop", "expr": "t_fixed + sum_plants(work) / team"},
                    ],
                    "parameters": {"a0": 6, "a1": 0.08, "t_fixed": 10},
                },
                "stats": {"n": 0},
            },
            [],
        ),
    ]


def run_smoketest(db: Session, progress=None) -> dict[str, Any]:
    progress = progress or (lambda f, m: None)
    resolver = SettingsResolver(db, None)
    rows: list[dict[str, Any]] = []
    cases = _cases()
    total = len(cases) + 4
    for i, (fn, text, ctx, images) in enumerate(cases):
        progress(i / total, f"{fn} …")
        started = time.monotonic()
        try:
            resp, model = ai.call(db, None, fn, text, images=images, context=ctx)
            rows.append(
                _row(
                    fn, model.label, True, started, resp.input_tokens, resp.output_tokens, _preview(resp.data)
                )
            )
        except AppError as exc:
            rows.append(
                _row(
                    fn,
                    _model_label(db, resolver, fn),
                    False,
                    started,
                    error=f"{exc.code} {exc.params.get('detail', '')}".strip(),
                )
            )
    # tool chats: voice control and settings assistant (one round, no changes are made)
    for fn in ("voice_command", "settings_assistant"):
        progress((len(rows)) / total, f"{fn} …")
        started = time.monotonic()
        try:
            resolved = ai.resolve_model(db, resolver, fn)
            provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
            key, _ = ai.api_key_for(db, None, resolver, resolved.provider)
            from app.api.voice import PAGES, TOOLS

            turn = provider.chat(
                resolved.model.model_name,
                "Du bedienst eine App. Antworte mit einem Werkzeugaufruf.",
                [{"role": "user", "content": "Öffne die Planung"}],
                TOOLS,
                key,
                {"mode": "voice", "pages": {k: list(v[1]) for k, v in PAGES.items()}, "effort": "low"},
            )
            ok = bool(turn.tool_calls) or bool(turn.text)
            preview = ", ".join(f"{c['name']}({c['input']})" for c in turn.tool_calls) or turn.text[:120]
            rows.append(
                _row(fn, resolved.model.label, ok, started, turn.input_tokens, turn.output_tokens, preview)
            )
        except (AppError, ProviderError) as exc:
            rows.append(
                _row(
                    fn,
                    _model_label(db, resolver, fn),
                    False,
                    started,
                    error=str(getattr(exc, "code", exc))[:200],
                )
            )
    # image generation (falls back to the local drawing without an image model)
    progress((len(rows)) / total, "plant_image …")
    started = time.monotonic()
    info = {
        "species": "Oleander",
        "height_cm": 160,
        "crown_width_cm": 90,
        "crown_shape": "sphere",
        "pot_diameter_cm": 50,
        "pot_height_cm": 45,
        "pot_shape": "round",
        "pot_material": "terracotta",
    }
    data, label, source = _image_for_platform(db, resolver, info)
    rows.append(
        _row(
            "plant_image",
            label,
            bool(data),
            started,
            preview=f"{len(data) // 1024} KB, {'Bildmodell' if source == 'model' else 'Zeichnung ohne Bildmodell'}",
        )
    )
    # transcription needs a real recording; only the configuration is checked
    started = time.monotonic()
    try:
        resolved = ai.resolve_model(db, resolver, "transcribe")
        ok = resolved.provider.kind in ("openai", "openai_compatible")
        rows.append(
            _row(
                "transcribe",
                resolved.model.label,
                ok,
                started,
                preview="eingestellt – bitte mit dem Mikrofon testen" if ok else None,
                error=None
                if ok
                else "kein Spracherkennungs-Modell (OpenAI) – der Browser erkennt die Sprache",
            )
        )
    except AppError as exc:
        rows.append(_row("transcribe", "–", False, started, error=exc.code))
    ok = sum(1 for r in rows if r["ok"])
    return {"rows": rows, "ok": ok, "failed": len(rows) - ok}


def _image_for_platform(
    db: Session, resolver: SettingsResolver, info: dict[str, Any]
) -> tuple[bytes, str, str]:
    from app.ai.images import prompt_for, render_plant

    try:
        resolved = ai.resolve_model(db, resolver, "plant_image")
    except AppError:
        return render_plant(info), "Zeichnung", "drawing"
    if resolved.provider.kind == "fake":
        return render_plant(info), resolved.model.label, "drawing"
    provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
    key, _ = ai.api_key_for(db, None, resolver, resolved.provider)
    try:
        return (
            provider.generate_image(resolved.model.model_name, prompt_for(info), key, {}),
            resolved.model.label,
            "model",
        )
    except (ProviderError, AttributeError) as exc:
        return b"", f"{resolved.model.label}: {exc}"[:120], "error"


def _model_label(db: Session, resolver: SettingsResolver, fn: str) -> str:
    try:
        return ai.resolve_model(db, resolver, fn).model.label
    except AppError:
        return "–"


def _preview(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)[:160] if data is not None else ""


def _row(fn, model, ok, started, tin=0, tout=0, preview=None, error=None) -> dict[str, Any]:
    return {
        "function": fn,
        "model": model,
        "ok": ok,
        "ms": int((time.monotonic() - started) * 1000),
        "input_tokens": tin,
        "output_tokens": tout,
        "preview": preview,
        "error": error,
    }

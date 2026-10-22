"""Plant images (round 2, package O): office and drivers see every plant as a picture.

A real photo always wins. A plant without a photo gets an AI image (``ai.model.plant_image``, e.g.
OpenAI gpt-image-1), clearly marked "KI-Bild". The image model only gets species and sizes of the
plant, never customer data. Without an image model (test model, or a model that cannot draw) the
picture is drawn locally from the plant's geometry, so there is always something to see.
"""

from __future__ import annotations

import io
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import AIResponse, ProviderError, get_provider
from app.core.context import system_actor
from app.core.errors import AppError
from app.models.orders import Photo, PickupOrder, Plant
from app.settings.service import SettingsResolver
from app.timemodel.plantfill import geometry

W, H = 600, 800
REAL_KINDS_FIRST = (
    "plant_front",
    "plant_side",
    "plant_top",
    "pot",
    "other",
    "pickup_proof",
    "delivery_proof",
)

# leaf and flower colours by species (substring of the German name)
LEAF = {
    "olive": (128, 144, 110),
    "oliv": (128, 144, 110),
    "lorbeer": (52, 92, 50),
    "palme": (64, 120, 62),
    "zitrus": (46, 104, 52),
    "zitrone": (46, 104, 52),
    "orange": (46, 104, 52),
    "oleander": (70, 110, 66),
    "feige": (74, 120, 58),
    "agave": (110, 150, 130),
}
FLOWERS = {
    "oleander": (226, 120, 160),
    "bougainvillea": (200, 40, 140),
    "zitrone": (240, 210, 60),
    "zitrus": (245, 170, 40),
    "orange": (245, 140, 30),
    "engelstrompete": (245, 225, 170),
    "hibiskus": (220, 60, 70),
    "enzian": (90, 80, 200),
}
POT_COLOURS = {
    "terracotta": (182, 98, 64),
    "glazed": (60, 86, 120),
    "wood": (140, 100, 62),
    "metal": (150, 154, 158),
    "stone": (170, 166, 156),
    "concrete": (160, 160, 158),
    "fiberglass": (90, 90, 96),
    "plastic": (70, 70, 74),
}


def _colour(table: dict[str, tuple[int, int, int]], name: str | None) -> tuple[int, int, int] | None:
    low = (name or "").lower()
    return next((c for k, c in table.items() if k in low), None)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def describe(plant: Plant) -> dict[str, Any]:
    """The plant data an image model gets (no customer data)."""
    g = geometry(plant)
    return {
        "species": plant.species_name or plant.label or "Kübelpflanze",
        "height_cm": round(g.total_h),
        "crown_width_cm": round(g.crown_w),
        "crown_shape": g.crown_shape,
        "pot_diameter_cm": round(g.pot_d),
        "pot_height_cm": round(g.pot_h),
        "pot_shape": g.pot_shape,
        "pot_material": plant.pot_material or "terracotta",
    }


def prompt_for(info: dict[str, Any]) -> str:
    shape = {
        "sphere": "runde Krone",
        "cone": "kegelförmige Krone",
        "column": "schmale Säulenform",
        "cylinder": "zylindrische Krone",
        "free": "frei gewachsene Krone",
    }.get(info["crown_shape"], "Krone")
    return (
        f"Realistisches Foto einer Kübelpflanze ({info['species']}), etwa {info['height_cm']} cm hoch, "
        f"{shape} etwa {info['crown_width_cm']} cm breit, in einem {info['pot_material']}-Topf mit "
        f"{info['pot_diameter_cm']} cm Durchmesser. Ganze Pflanze mit Topf, seitliche Ansicht, freigestellt "
        "vor hellem, neutralem Hintergrund, Tageslicht. Keine Menschen, kein Text, keine Wasserzeichen."
    )


def render_plant(info: dict[str, Any]) -> bytes:
    """Local drawing of the plant to scale (used without an image model)."""
    img = Image.new("RGB", (W, H), (244, 241, 233))
    d = ImageDraw.Draw(img)
    total = max(40.0, float(info["height_cm"]))
    pot_h = min(float(info["pot_height_cm"]), total * 0.6)
    pot_d = float(info["pot_diameter_cm"])
    crown_w = float(info["crown_width_cm"])
    scale = min((H - 170) / total, (W - 140) / max(crown_w, pot_d * 1.1, 1))
    ground = H - 90
    cx = W // 2 - 20
    # ruler with the height
    rx = W - 70
    top = ground - total * scale
    d.line([(rx, ground), (rx, top)], fill=(120, 120, 110), width=2)
    for y in (ground, top):
        d.line([(rx - 8, y), (rx + 8, y)], fill=(120, 120, 110), width=2)
    label = f"{total / 100:.2f} m".replace(".", ",")
    d.text((rx - 30, top - 30), label, fill=(80, 80, 72), font=_font(22))
    d.line([(30, ground), (W - 30, ground)], fill=(200, 194, 180), width=2)
    # pot (tapered for round pots)
    pw, ph = pot_d * scale, pot_h * scale
    taper = 0.82 if info["pot_shape"] == "round" else 0.96
    pot_col = POT_COLOURS.get(info["pot_material"], POT_COLOURS["terracotta"])
    d.polygon(
        [
            (cx - pw / 2, ground - ph),
            (cx + pw / 2, ground - ph),
            (cx + pw * taper / 2, ground),
            (cx - pw * taper / 2, ground),
        ],
        fill=pot_col,
    )
    d.rectangle([cx - pw / 2 - 4, ground - ph - 10, cx + pw / 2 + 4, ground - ph], fill=pot_col)
    leaf = _colour(LEAF, info["species"]) or (66, 112, 60)
    dark = tuple(max(0, c - 28) for c in leaf)
    flower = _colour(FLOWERS, info["species"])
    crown_h = max(20.0, total - pot_h) * scale
    cw = crown_w * scale
    base = ground - ph - 10
    name = info["species"].lower()
    if "palme" in name:
        trunk_top = base - crown_h * 0.55
        d.line([(cx, base), (cx, trunk_top)], fill=(122, 96, 66), width=max(6, int(pw * 0.12)))
        for k in range(11):
            a = math.pi * (0.1 + 0.8 * k / 10)
            ex, ey = cx + math.cos(a) * cw / 2 * -1, trunk_top - math.sin(a) * crown_h * 0.45
            d.line([(cx, trunk_top), (ex, ey)], fill=leaf if k % 2 else dark, width=7)
    else:
        trunk_top = base - crown_h * 0.25
        d.line([(cx, base), (cx, trunk_top)], fill=(110, 86, 60), width=max(5, int(pw * 0.08)))
        box = [cx - cw / 2, base - crown_h, cx + cw / 2, trunk_top + crown_h * 0.1]
        shape = info["crown_shape"]
        if shape == "cone":
            d.polygon([(cx, box[1]), (box[2], box[3]), (box[0], box[3])], fill=leaf)
        elif shape in ("column", "cylinder"):
            d.rounded_rectangle(
                [cx - cw * 0.32, box[1], cx + cw * 0.32, box[3]], radius=int(cw * 0.3), fill=leaf
            )
        else:
            d.ellipse(box, fill=leaf)
            for k in range(7):  # some depth in the crown
                a = 2 * math.pi * k / 7
                r = cw * 0.18
                px, py = cx + math.cos(a) * cw * 0.22, (box[1] + box[3]) / 2 + math.sin(a) * crown_h * 0.18
                d.ellipse([px - r, py - r, px + r, py + r], fill=dark if k % 2 else leaf)
        if flower:
            for k in range(26):
                a = k * 2.399  # golden angle spreads the dots evenly
                rr = math.sqrt(k / 26) * 0.42
                px = cx + math.cos(a) * cw * rr
                py = (box[1] + box[3]) / 2 + math.sin(a) * crown_h * rr * 0.8
                d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=flower)
    d.text((24, 20), info["species"], fill=(40, 52, 38), font=_font(30))
    d.text(
        (24, 58),
        f"Topf Ø {round(pot_d)} cm · Krone {round(crown_w)} cm",
        fill=(90, 96, 84),
        font=_font(20),
    )
    d.rounded_rectangle([24, H - 52, 150, H - 20], radius=12, fill=(60, 86, 62))
    d.text((38, H - 47), "KI-Bild", fill=(255, 255, 255), font=_font(20))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _real_photo(db: Session, plant: Plant) -> Photo | None:
    photos = list(db.scalars(select(Photo).where(Photo.plant_id == plant.id, Photo.kind != "generated")))
    photos.sort(
        key=lambda p: (REAL_KINDS_FIRST.index(p.kind) if p.kind in REAL_KINDS_FIRST else 99, p.position)
    )
    return photos[0] if photos else None


def _generated(db: Session, plant: Plant) -> Photo | None:
    return db.scalar(
        select(Photo)
        .where(Photo.plant_id == plant.id, Photo.kind == "generated")
        .order_by(Photo.created_at.desc())
        .limit(1)
    )


def plant_image(db: Session, plant: Plant) -> dict[str, Any] | None:
    """{url, generated} of the picture to show for a plant: real photo first, else the AI image."""
    p = _real_photo(db, plant)
    if p is not None:
        return {"url": f"/api/files/{p.file_id}", "generated": False, "photo_id": p.id}
    g = _generated(db, plant)
    if g is not None:
        return {"url": f"/api/files/{g.file_id}", "generated": True, "photo_id": g.id}
    return None


def images_for(db: Session, plants: list[Plant]) -> dict[uuid.UUID, dict[str, Any] | None]:
    return {p.id: plant_image(db, p) for p in plants}


def _draw_with_model(
    db: Session, tenant_id: uuid.UUID, info: dict[str, Any], job_id: uuid.UUID | None
) -> tuple[bytes, str, str]:
    """(png bytes, model label, source). Falls back to the local drawing if no image model is set."""
    from app.ai.service import _record, api_key_for, resolve_model

    resolver = SettingsResolver(db, tenant_id)
    try:
        resolved = resolve_model(db, resolver, "plant_image")
    except AppError:
        return render_plant(info), "Zeichnung", "drawing"
    if resolved.provider.kind == "fake":
        return render_plant(info), resolved.model.label, "drawing"
    provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
    key, key_mode = api_key_for(db, tenant_id, resolver, resolved.provider)
    started = datetime.now(UTC)
    try:
        data = provider.generate_image(resolved.model.model_name, prompt_for(info), key, {})
    except (ProviderError, AttributeError) as exc:
        _record(
            tenant_id,
            "plant_image",
            resolved.provider,
            resolved.model,
            key_mode,
            None,
            0,
            False,
            str(exc),
            job_id,
        )
        return render_plant(info), "Zeichnung", "drawing"
    ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    price = float(resolver.get("ai.image_price_eur"))
    _record(
        tenant_id,
        "plant_image",
        resolved.provider,
        resolved.model,
        key_mode,
        AIResponse(text="", duration_ms=ms),
        price,
        True,
        None,
        job_id,
    )
    return data, resolved.model.label, "model"


def generate_for_plant(
    db: Session, plant: Plant, job_id: uuid.UUID | None = None, force: bool = False
) -> Photo | None:
    """AI image for a plant without a real photo (or a new one with force)."""
    from app.api.files import store_file

    if not force and (_real_photo(db, plant) is not None or _generated(db, plant) is not None):
        return None
    info = describe(plant)
    data, model, source = _draw_with_model(db, plant.tenant_id, info, job_id)
    media = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
    actor = system_actor(plant.tenant_id, label="KI-Bild")
    stored = store_file(db, actor, data, f"ki-bild-{plant.number}.png", media, "photo")
    for old in db.scalars(select(Photo).where(Photo.plant_id == plant.id, Photo.kind == "generated")):
        db.delete(old)
    photo = Photo(
        tenant_id=plant.tenant_id,
        file_id=stored.id,
        kind="generated",
        order_id=plant.order_id,
        plant_id=plant.id,
        width_px=width,
        height_px=height,
        quality={},
        a4={},
        a4_detected=False,
        ai_results={
            "generated": {"model": model, "source": source, "info": info, "at": datetime.now(UTC).isoformat()}
        },
        caption=f"KI-Bild: {info['species']}",
    )
    db.add(photo)
    db.flush()
    return photo


def generate_for_order(
    db: Session, order: PickupOrder, job_id: uuid.UUID | None = None, force: bool = False
) -> int:
    source = order.return_of_id or order.id
    n = 0
    for plant in db.scalars(select(Plant).where(Plant.order_id == source, Plant.deleted_at.is_(None))):
        if generate_for_plant(db, plant, job_id=job_id, force=force) is not None:
            n += 1
    return n

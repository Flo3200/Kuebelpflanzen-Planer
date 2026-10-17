"""AI intake: message (+ photos) -> draft with confidences -> (human confirms) -> real records.

Also: photo completeness check and photo analysis for existing orders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai import service as ai
from app.ai.providers import AIImage
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.i18n import catalog
from app.models.masterdata import Species
from app.models.orders import Address, Customer, Draft, Photo, PickupOrder, Plant, StoredFile
from app.settings.service import SettingsResolver
from app.storage.backend import get_storage

REQUIRED_FIELDS = ("customer.name", "address.street", "address.postal_code", "address.city")


def kind_labels() -> dict[str, str]:
    return catalog().get("photo_kinds", {})


def _images(db: Session, photos: list[Photo], limit: int = 12) -> list[AIImage]:
    labels = kind_labels()
    out = []
    for i, p in enumerate(photos[:limit], start=1):
        stored = db.get(StoredFile, p.file_id)
        if stored is None:
            continue
        try:
            data = get_storage().get(stored.key)
        except FileNotFoundError:
            continue
        scale = ""
        if p.a4 and p.a4.get("detected") and p.a4.get("cm_per_px"):
            scale = f", A4 erkannt: {p.a4['cm_per_px']} cm/Pixel"
        out.append(
            AIImage(
                data=data,
                media_type=stored.content_type,
                label=f"Bild {i}: {labels.get(p.kind, p.kind)}{scale}",
            )
        )
    return out


def _photo_context(photos: list[Photo]) -> list[dict[str, Any]]:
    return [
        {"kind": p.kind, "quality": p.quality, "a4": p.a4, "width": p.width_px, "height": p.height_px}
        for p in photos
    ]


def species_names(db: Session, tenant_id: uuid.UUID) -> list[str]:
    from app.api.masterdata import visible_species

    names: list[str] = []
    for s in visible_species(db, tenant_id):
        names.append(s.name)
        names += [str(a) for a in (s.aliases or [])]
    return names


def match_species(db: Session, tenant_id: uuid.UUID, name: str | None) -> Species | None:
    if not name:
        return None
    from app.api.masterdata import visible_species

    low = name.lower().strip()
    best = None
    for s in visible_species(db, tenant_id):
        candidates = [s.name, s.botanical_name or "", *[str(a) for a in (s.aliases or [])]]
        for c in candidates:
            c = c.lower()
            if not c:
                continue
            if c == low:
                return s
            if best is None and (
                low.startswith(c[: max(4, len(c) - 2)]) or c.startswith(low[: max(4, len(low) - 2)])
            ):
                best = s
    return best


def flatten_confidence(extracted: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict) and set(node) == {"value", "confidence"}:
            out[path] = float(node.get("confidence") or 0) if node.get("value") is not None else 0.0
        elif isinstance(node, dict):
            for k, val in node.items():
                walk(val, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, val in enumerate(node):
                walk(val, f"{path}[{i}]")

    for section in ("customer", "address", "order", "plants", "path"):
        walk(extracted.get(section), section)
    return out


def _value(node: Any) -> Any:
    return node.get("value") if isinstance(node, dict) else node


def process_draft(
    db: Session, tenant_id: uuid.UUID, draft_id: uuid.UUID, job_id: uuid.UUID | None = None
) -> Draft:
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise NotFound()
    resolver = SettingsResolver(db, tenant_id)
    photos = list(
        db.scalars(select(Photo).where(Photo.draft_id == draft.id).order_by(Photo.position, Photo.created_at))
    )
    context = {
        "species_names": species_names(db, tenant_id),
        "today": date.today().isoformat(),
        "photo_count": len(photos),
        "message": draft.source_text,
    }
    text = (
        f"Heute ist der {date.today().strftime('%d.%m.%Y')}.\n"
        f"Pflanzenarten-Katalog: {', '.join(sorted(set(context['species_names']))[:200])}\n\n"
        f'Nachricht ({draft.source_kind}):\n"""\n{draft.source_text}\n"""\n'
        f"Anzahl Fotos: {len(photos)}"
    )
    resp, model = ai.call(
        db, tenant_id, "message_intake", text, images=_images(db, photos), context=context, job_id=job_id
    )
    extracted = resp.data
    photo_check: dict[str, Any] = {}
    if photos:
        photo_check = completeness(db, tenant_id, photos, job_id=job_id)
        analysis = analyse_photos(db, tenant_id, photos, job_id=job_id)
        _merge_analysis(extracted, analysis)
    threshold = float(resolver.get("photos.min_confidence"))
    conf = flatten_confidence(extracted)
    review = [k for k, c in conf.items() if c < threshold and _is_set(extracted, k)]
    review += [k for k in REQUIRED_FIELDS if conf.get(k, 0) == 0]
    draft.extracted = extracted
    draft.confidence = conf
    draft.review_fields = sorted(set(review))
    draft.photo_check = photo_check
    draft.follow_up = extracted.get("follow_up_message") or None
    if photo_check.get("feedback") and draft.follow_up is None:
        draft.follow_up = (
            "Guten Tag,\n\nbitte schicken Sie uns noch folgende Fotos: "
            + "; ".join(photo_check["feedback"])
            + "\n\nVielen Dank!"
        )
    draft.model = model.label
    draft.status = "review"
    draft.error = None
    db.flush()
    return draft


def _is_set(extracted: dict[str, Any], path: str) -> bool:
    node: Any = extracted
    for part in path.replace("]", "").replace("[", ".").split("."):
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return False
    return _value(node) is not None


def _merge_analysis(extracted: dict[str, Any], analysis: dict[str, Any]) -> None:
    """Fill values from photo analysis where the message gave nothing (or less confidence)."""
    plants = extracted.get("plants") or []
    pa = analysis.get("plant") or {}
    if len(plants) == 1:
        target = plants[0]
        mapping = {
            "total_height_cm": "total_height_cm",
            "crown_width_cm": "crown_width_cm",
            "pot_diameter_cm": "pot_diameter_cm",
            "pot_height_cm": "pot_height_cm",
            "weight_kg": "weight_kg",
            "species": "species",
        }
        for src, dst in mapping.items():
            new = pa.get(src) or {}
            old = target.get(dst) or {"value": None, "confidence": 0}
            if new.get("value") is not None and (
                old.get("value") is None or new.get("confidence", 0) > old.get("confidence", 0)
            ):
                target[dst] = new
    path = extracted.get("path") or {}
    for k, new in (analysis.get("path") or {}).items():
        if (
            k in path
            and new.get("value") is not None
            and (path[k].get("value") is None or new.get("confidence", 0) > path[k].get("confidence", 0))
        ):
            path[k] = new


def completeness(
    db: Session, tenant_id: uuid.UUID, photos: list[Photo], job_id: uuid.UUID | None = None, plants: int = 1
) -> dict[str, Any]:
    resolver = SettingsResolver(db, tenant_id)
    required = list(resolver.get("photos.plant_set")) + list(resolver.get("photos.path_set"))
    required = [k for k in required if k != "path_segment"]
    labels = kind_labels()
    context = {"photos": _photo_context(photos), "required_kinds": required, "kind_labels": labels}
    text = (
        "Erwartete Fotoarten: " + ", ".join(labels.get(k, k) for k in required) + "\n"
        "Lokale Bildprüfung (Schärfe, Belichtung, A4-Erkennung) je Foto:\n"
        + "\n".join(
            f"Bild {i}: {labels.get(p.kind, p.kind)}; scharf={p.quality.get('sharp')}; belichtung_ok={p.quality.get('exposure_ok')}; "
            f"A4={'ja' if p.a4_detected else 'nein'}"
            for i, p in enumerate(photos, start=1)
        )
    )
    resp, _ = ai.call(
        db, tenant_id, "completeness_check", text, images=_images(db, photos), context=context, job_id=job_id
    )
    result = resp.data
    # local checks are authoritative for sharpness/exposure/A4 detection; AI adds content checks
    result["checked_at"] = datetime.now(UTC).isoformat()
    return result


def analyse_photos(
    db: Session, tenant_id: uuid.UUID, photos: list[Photo], job_id: uuid.UUID | None = None
) -> dict[str, Any]:
    context = {"photos": _photo_context(photos)}
    labels = kind_labels()
    text = "Fotos:\n" + "\n".join(
        f"Bild {i}: {labels.get(p.kind, p.kind)}, {p.width_px}×{p.height_px} px"
        + (f", A4-Maßstab {p.a4.get('cm_per_px')} cm/px" if p.a4_detected else "")
        for i, p in enumerate(photos, start=1)
    )
    resp, _ = ai.call(
        db, tenant_id, "photo_analysis", text, images=_images(db, photos), context=context, job_id=job_id
    )
    for p in photos:
        p.ai_results = {"analysis": resp.data, "at": datetime.now(UTC).isoformat()}
    return resp.data


def apply_analysis_to_plant(
    db: Session, plant: Plant, analysis: dict[str, Any], threshold: float
) -> list[str]:
    """Write analysed values into a plant where the current value is only an estimate."""
    from app.timemodel.plantfill import complete_plant

    changed = []
    pa = analysis.get("plant") or {}
    for field in (
        "total_height_cm",
        "crown_width_cm",
        "crown_height_cm",
        "pot_diameter_cm",
        "pot_height_cm",
        "weight_kg",
    ):
        node = pa.get(field) or {}
        val, conf = node.get("value"), float(node.get("confidence") or 0)
        if val is None or conf < threshold * 0.5:
            continue
        if getattr(plant, field) is None or field in (plant.estimated_fields or []):
            setattr(plant, field, val)
            plant.field_confidence = {**(plant.field_confidence or {}), field: conf}
            plant.estimated_fields = [f for f in (plant.estimated_fields or []) if f != field] + (
                [field] if conf < threshold else []
            )
            changed.append(field)
    if changed:
        complete_plant(db, plant, SettingsResolver(db, plant.tenant_id))
    return changed


# ------------------------------------------------------------------------------- confirmation


def _segments_from_path(path: dict[str, Any]) -> list[dict[str, Any]]:
    length = _value(path.get("length_m"))
    steps = _value(path.get("steps")) or 0
    height = _value(path.get("height_m"))
    width = _value(path.get("min_width_cm"))
    elevator = _value(path.get("elevator"))
    surface = _value(path.get("surface")) or "paved"
    length = float(length) if length is not None else None
    segments: list[dict[str, Any]] = []
    if elevator:
        half = (length or 20) / 2
        segments = [
            {"kind": "flat", "length_m": half, "surface": surface},
            {"kind": "elevator", "length_m": 2, "elevator": True, "height_diff_m": height or 0},
            {"kind": "flat", "length_m": half, "surface": "paved"},
        ]
    elif steps:
        stair_len = round(steps * 0.3, 1)
        rest = max(1.0, (length or stair_len + 10) - stair_len)
        segments = [
            {"kind": "flat", "length_m": round(rest * 0.4, 1), "surface": surface},
            {
                "kind": "stairs",
                "length_m": stair_len,
                "steps": int(steps),
                "height_diff_m": height or round(steps * 0.17, 2),
            },
            {"kind": "flat", "length_m": round(rest * 0.6, 1), "surface": "paved"},
        ]
    elif length is not None:
        segments = [{"kind": "flat", "length_m": length, "surface": surface}]
    if width and segments:
        target = next((s for s in segments if s["kind"] == "stairs"), segments[0])
        target["min_width_cm"] = float(width)
        if float(width) < 90 and target["kind"] == "flat":
            target["kind"] = "narrow"
    return segments


def _find_customer(
    db: Session, tenant_id: uuid.UUID, email: str | None, phone: str | None
) -> Customer | None:
    conds = []
    if email:
        conds.append(func.lower(Customer.email) == email.lower())
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) >= 6:
            conds.append(func.regexp_replace(Customer.phone, r"\D", "", "g") == digits)
    if not conds:
        return None
    return db.scalar(
        select(Customer)
        .where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None), or_(*conds))
        .limit(1)
    )


def confirm_draft(
    db: Session,
    actor: Actor,
    draft: Draft,
    extracted: dict[str, Any] | None = None,
    order_status: str = "confirmed",
) -> dict[str, Any]:
    from app.api.orders import create_path, create_plant, new_order

    if draft.status not in ("review", "new", "failed"):
        raise AppError("errors.draft_not_pending")
    tid = actor.require_tenant()
    data = extracted if extracted is not None else draft.extracted
    c, a, o = data.get("customer") or {}, data.get("address") or {}, data.get("order") or {}
    name = _value(c.get("name"))
    street, plz, city = _value(a.get("street")), _value(a.get("postal_code")), _value(a.get("city"))
    if not name or not street or not plz or not city:
        raise AppError("errors.validation")
    customer = _find_customer(db, tid, _value(c.get("email")), _value(c.get("phone")))
    created_customer = customer is None
    if customer is None:
        customer = Customer(tenant_id=tid, name=name, source="ai_draft")
        db.add(customer)
    for field in ("company", "email", "phone"):
        if _value(c.get(field)) and not getattr(customer, field):
            setattr(customer, field, _value(c.get(field)))
    if draft.photo_check or draft.source_kind in ("email", "text"):
        # the customer sent the photos themselves; consent is documented with the draft
        if not customer.consent_photos and any(
            True for _ in db.scalars(select(Photo.id).where(Photo.draft_id == draft.id).limit(1))
        ):
            customer.consent_photos = True
            customer.consent_at = datetime.now(UTC)
            customer.consent_text = "Fotos vom Kunden selbst geschickt (Entwurf)"
    customer.last_activity_at = datetime.now(UTC)
    db.flush()
    address = db.scalar(
        select(Address).where(
            Address.customer_id == customer.id,
            func.lower(Address.street) == street.lower(),
            Address.postal_code == plz,
            Address.deleted_at.is_(None),
        )
    )
    if address is None:
        address = Address(tenant_id=tid, customer_id=customer.id, street=street, postal_code=plz, city=city)
        db.add(address)
    if _value(a.get("parking_notes")):
        address.parking_notes = _value(a.get("parking_notes"))
    notes_bits = [x for x in (_value(a.get("floor")), _value(a.get("access_notes"))) if x]
    if notes_bits:
        address.access_notes = "; ".join(notes_bits)
    db.flush()
    from app.api.orders import _geocode_hook

    _geocode_hook(db, actor, address, True)

    def as_date(x: Any) -> date | None:
        try:
            return date.fromisoformat(str(x)) if x else None
        except ValueError:
            return None

    order = new_order(
        db,
        actor,
        {
            "customer_id": customer.id,
            "address_id": address.id,
            "earliest_date": as_date(_value(o.get("earliest_date"))),
            "latest_date": as_date(_value(o.get("latest_date"))),
            "notes": _value(o.get("notes")),
        },
    )
    order.source = "ai_draft"
    order.status = order_status
    path_data = data.get("path") or {}
    segments = _segments_from_path(path_data)
    path = create_path(
        db,
        actor,
        order,
        {
            "name": _value(path_data.get("description")) or "Weg",
            "length_confirmed_m": _value(path_data.get("length_m")),
        },
        segments,
        confidence={k: (v or {}).get("confidence") for k, v in path_data.items() if isinstance(v, dict)},
    )
    plants_created: list[Plant] = []
    for p in data.get("plants") or []:
        count = int(_value(p.get("count")) or 1)
        species = match_species(db, tid, _value(p.get("species")))
        values = {
            "label": _value(p.get("label")),
            "species_id": species.id if species else None,
            "pot_diameter_cm": _value(p.get("pot_diameter_cm")),
            "pot_height_cm": _value(p.get("pot_height_cm")),
            "total_height_cm": _value(p.get("total_height_cm")),
            "crown_width_cm": _value(p.get("crown_width_cm")),
            "weight_kg": _value(p.get("weight_kg")),
            "notes": _value(p.get("notes")),
        }
        conf = {
            k: float((p.get(k) or {}).get("confidence") or 0) for k in values if isinstance(p.get(k), dict)
        }
        for i in range(max(1, min(count, 50))):
            vals = dict(values)
            if count > 1 and vals["label"]:
                vals["label"] = f"{vals['label']} {i + 1}/{count}"
            plants_created.append(create_plant(db, actor, order, vals, confidence=conf, path_id=path.id))
    # move the photos from the draft to the order (and to the plant if there is exactly one)
    for photo in db.scalars(select(Photo).where(Photo.draft_id == draft.id)):
        photo.order_id = order.id
        if photo.kind.startswith("path"):
            photo.path_id = path.id
        elif len(plants_created) == 1:
            photo.plant_id = plants_created[0].id
    draft.status = "confirmed"
    draft.confirmed_by = actor.user_id
    draft.confirmed_at = datetime.now(UTC)
    draft.customer_id = customer.id
    draft.order_id = order.id
    if extracted is not None:
        draft.extracted = extracted
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="draft",
        entity_id=draft.id,
        action="confirm",
        new={"customer_id": str(customer.id), "order_id": str(order.id), "plants": len(plants_created)},
    )
    db.flush()
    try:
        from app.timemodel.service import refresh_order_estimate

        refresh_order_estimate(db, order)
    except ModuleNotFoundError:
        pass
    return {
        "customer_id": customer.id,
        "customer_created": created_customer,
        "order_id": order.id,
        "order_number": order.number,
        "plants": [pl.id for pl in plants_created],
        "path_id": path.id,
    }


def order_photos(db: Session, order: PickupOrder) -> list[Photo]:
    return list(
        db.scalars(
            select(Photo)
            .where(Photo.order_id == (order.return_of_id or order.id))
            .order_by(Photo.kind, Photo.position)
        )
    )

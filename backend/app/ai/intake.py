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
from app.timemodel import knowledge

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
        kind = "noch nicht zugeordnet" if _unsorted(p) else labels.get(p.kind, p.kind)
        plant_no = _plant_no(p)
        out.append(
            AIImage(
                data=data,
                media_type=stored.content_type,
                label=f"Bild {i}: {kind}{f', Pflanze {plant_no}' if plant_no else ''}{scale}",
            )
        )
    return out


def _unsorted(p: Photo) -> bool:
    """Pasted without a kind and not yet sorted by the AI."""
    ai_results = p.ai_results or {}
    return bool(ai_results.get("auto")) and "sorted" not in ai_results


def _plant_no(p: Photo) -> int | None:
    """Number of the plant (1-based, order of the draft's plant list) the AI assigned the photo to."""
    sorted_ = (p.ai_results or {}).get("sorted") or {}
    n = sorted_.get("plant")
    return int(n) if isinstance(n, int) and n > 0 else None


def _photo_context(photos: list[Photo]) -> list[dict[str, Any]]:
    return [
        {
            "kind": p.kind,
            "plant": _plant_no(p),
            "quality": p.quality,
            "a4": p.a4,
            "width": p.width_px,
            "height": p.height_px,
        }
        for p in photos
    ]


def _plant_names(plants: list[dict[str, Any]]) -> list[str]:
    out = []
    for i, p in enumerate(plants, start=1):
        name = _value(p.get("species")) or _value(p.get("label")) or "Pflanze"
        count = _value(p.get("count")) or 1
        out.append(
            f"{name}{f' ({count} Stück)' if count and int(count) > 1 else ''}" if name else f"Pflanze {i}"
        )
    return out


def sort_photos(
    db: Session,
    tenant_id: uuid.UUID,
    photos: list[Photo],
    plants: list[dict[str, Any]],
    job_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """AI assigns pasted photos: kind (front, side, pot, path …) and the plant they show."""
    from app.ai.functions import SORT_KINDS

    names = _plant_names(plants)
    text = (
        "Pflanzen laut Nachricht:\n"
        + ("\n".join(f"Pflanze {i}: {n}" for i, n in enumerate(names, start=1)) or "keine genannt")
        + "\n\nFotos (lokale Prüfung):\n"
        + "\n".join(
            f"Bild {i}: {p.width_px}×{p.height_px} px, A4-Blatt {'erkannt' if p.a4_detected else 'nicht erkannt'}"
            for i, p in enumerate(photos, start=1)
        )
    )
    context = {"photos": _photo_context(photos), "plants": names}
    resp, _ = ai.call(
        db, tenant_id, "photo_sort", text, images=_images(db, photos), context=context, job_id=job_id
    )
    result = resp.data or {}
    for item in result.get("photos") or []:
        idx = int(item.get("index") or 0) - 1
        if not 0 <= idx < len(photos):
            continue
        p = photos[idx]
        kind = item.get("kind")
        if kind in SORT_KINDS:
            p.kind = kind
        plant = item.get("plant")
        p.ai_results = {
            **(p.ai_results or {}),
            "sorted": {
                "kind": kind,
                "plant": int(plant) if isinstance(plant, int) and not kind.startswith("path") else None,
                "confidence": item.get("confidence"),
                "description": item.get("description"),
            },
        }
    for p in photos:  # photos the AI skipped keep their place, but count as sorted
        if _unsorted(p):
            p.ai_results = {**(p.ai_results or {}), "sorted": {"kind": p.kind, "plant": None}}
    db.flush()
    return result


def _add_plants_from_photos(extracted: dict[str, Any], photos: list[Photo]) -> None:
    """Plants that only appear on photos (not in the text) get their own entry."""
    plants = extracted.setdefault("plants", [])
    highest = max((_plant_no(p) or 0 for p in photos), default=0)
    while len(plants) < highest:
        n = len(plants) + 1
        plants.append(
            {
                "label": {"value": f"Pflanze {n} (nur auf Fotos)", "confidence": 0.5},
                "species": {"value": None, "confidence": 0},
                "count": {"value": 1, "confidence": 0.6},
                **{
                    k: {"value": None, "confidence": 0}
                    for k in (
                        "pot_diameter_cm",
                        "pot_height_cm",
                        "total_height_cm",
                        "crown_width_cm",
                        "weight_kg",
                        *knowledge.AI_TRAITS,
                        "location",
                        "notes",
                    )
                },
            }
        )


def species_names(db: Session, tenant_id: uuid.UUID) -> list[str]:
    return knowledge.names(db, tenant_id)


def match_species(db: Session, tenant_id: uuid.UUID, name: str | None) -> Species | None:
    return knowledge.match(db, tenant_id, name)


def species_traits(db: Session, tenant_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Knowledge-base properties per species name (context for the test model)."""
    out: dict[str, dict[str, Any]] = {}
    for s in knowledge.catalog(db, tenant_id):
        traits = knowledge.traits_of(s)
        for n in (s.name, *[str(a) for a in (s.aliases or [])]):
            out[n] = traits
    return out


def apply_traits(plant: Plant, node: dict[str, Any], threshold: float) -> list[str]:
    """Species and properties from an AI result onto a plant; weak values are left to the knowledge base.

    A value is taken when the plant has none yet or only an estimate; values below half the review
    threshold are ignored, values below the threshold stay marked as estimated.
    """
    changed: list[str] = []
    estimated = set(plant.estimated_fields or [])
    conf_map = dict(plant.field_confidence or {})
    for src, field in (("species", "species_name"), *[(t, t) for t in knowledge.AI_TRAITS]):
        item = node.get(src) if isinstance(node.get(src), dict) else None
        if not item:
            continue
        val, conf = item.get("value"), float(item.get("confidence") or 0)
        if val is None or conf < threshold * 0.5:
            continue
        current = getattr(plant, field)
        if current is not None and field not in estimated and field in conf_map and conf <= conf_map[field]:
            continue  # a person or a surer result set it
        if current is not None and field not in estimated and field not in conf_map:
            continue  # entered by a person
        setattr(plant, field, val)
        conf_map[field] = conf
        if conf < threshold:
            estimated.add(field)
        else:
            estimated.discard(field)
        changed.append(field)
    if "species_name" in changed:
        plant.species_id = None  # looked up again in the knowledge base
        plant.species_source = "ai"
    plant.field_confidence = conf_map
    plant.estimated_fields = sorted(estimated)
    return changed


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
        "species_traits": species_traits(db, tenant_id),
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
    if any(_unsorted(p) for p in photos):
        sort_photos(db, tenant_id, photos, extracted.get("plants") or [], job_id=job_id)
        _add_plants_from_photos(extracted, photos)
    if photos:
        photo_check = completeness(
            db, tenant_id, photos, job_id=job_id, plant_names=_plant_names(extracted.get("plants") or [])
        )
        _analyse_into(db, tenant_id, extracted, photos, job_id)
    threshold = float(resolver.get("photos.min_confidence"))
    conf = flatten_confidence(extracted)
    # species properties are background values (knowledge base as fallback), not review fields
    review = [
        k
        for k, c in conf.items()
        if c < threshold and _is_set(extracted, k) and k.rsplit(".", 1)[-1] not in knowledge.AI_TRAITS
    ]
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
    _request_missing(db, tenant_id, draft, resolver, job_id)
    return draft


def _analyse_into(
    db: Session,
    tenant_id: uuid.UUID,
    extracted: dict[str, Any],
    photos: list[Photo],
    job_id: uuid.UUID | None,
) -> None:
    """Photo analysis per plant (photos the AI assigned to it) and once for the path photos."""
    plants = extracted.get("plants") or []
    groups: dict[int, list[Photo]] = {}
    for p in photos:
        n = _plant_no(p)
        if n and not p.kind.startswith("path"):
            groups.setdefault(n, []).append(p)
    path_photos = [p for p in photos if p.kind.startswith("path")]
    if not groups:
        # kinds given by hand, no plant numbers: one analysis, plant values only for a single plant
        analysis = analyse_photos(db, tenant_id, photos, job_id=job_id)
        if len(plants) == 1:
            _merge_plant(plants[0], analysis.get("plant") or {})
        _merge_path(extracted, analysis.get("path") or {})
        return
    first = True
    for n, group in sorted(groups.items()):
        analysis = analyse_photos(db, tenant_id, group + (path_photos if first else []), job_id=job_id)
        if n <= len(plants):
            _merge_plant(plants[n - 1], analysis.get("plant") or {})
        if first:
            _merge_path(extracted, analysis.get("path") or {})
        first = False


def _contact_wanted(resolver: SettingsResolver) -> bool:
    return bool(resolver.get("privacy.store_contact"))


def _request_missing(
    db: Session,
    tenant_id: uuid.UUID,
    draft: Draft,
    resolver: SettingsResolver,
    job_id: uuid.UUID | None,
) -> None:
    """If photos or details are missing: the AI writes the message to the customer, the office gets a
    notification with it (and, with the share module, a personal upload link for the customer)."""
    from app.i18n import t
    from app.notify.service import close_for_draft, create_share_link, notify, share_enabled

    ex = draft.extracted or {}
    missing = [m for m in ex.get("missing") or [] if "kontakt" not in m.lower()]
    feedback = list((draft.photo_check or {}).get("feedback") or [])
    if not draft.photo_check and not db.scalar(select(Photo.id).where(Photo.draft_id == draft.id).limit(1)):
        feedback = feedback or ["Es wurden noch keine Fotos geschickt."]
    if not (missing or feedback):
        close_for_draft(db, draft.id, "photos_missing")
        return
    if not resolver.get("notify.missing_photos"):
        return
    from app.models.notify import Notification

    previous = db.scalar(
        select(Notification)
        .where(Notification.draft_id == draft.id, Notification.kind == "photos_missing")
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    link = (previous.data or {}).get("share_url") if previous else None
    if link is None and share_enabled(db, tenant_id):
        _, link = create_share_link(db, tenant_id, draft_id=draft.id)
    try:
        message = write_follow_up(db, tenant_id, ex, missing, feedback, link, job_id)
    except AppError:
        message = draft.follow_up  # AI not reachable: keep the message from the intake
    if message:
        draft.follow_up = message
    who = _value((ex.get("customer") or {}).get("name")) or (draft.source_text or "")[:40] or "Entwurf"
    notify(
        db,
        tenant_id,
        "photos_missing",
        t("notifications.photos_missing", who=who),
        body=t("notifications.photos_missing_body"),
        message=draft.follow_up,
        link=f"/betrieb/posteingang/{draft.id}",
        draft_id=draft.id,
        data={"missing": missing, "feedback": feedback, "share_url": link},
    )


def write_follow_up(
    db: Session,
    tenant_id: uuid.UUID,
    extracted: dict[str, Any],
    missing: list[str],
    feedback: list[str],
    link: str | None,
    job_id: uuid.UUID | None = None,
) -> str:
    """The AI formulates the request for the missing photos and details (function follow_up)."""
    from app.models.core import Tenant

    tenant = db.get(Tenant, tenant_id)
    name = _value((extracted.get("customer") or {}).get("name"))
    plants = _plant_names(extracted.get("plants") or [])
    text = (
        f"Betrieb: {tenant.name if tenant else ''}\n"
        f"Kunde: {name or 'Name unbekannt'}\n"
        f"Pflanzen: {'; '.join(f'Pflanze {i}: {n}' for i, n in enumerate(plants, start=1)) or 'noch keine'}\n"
        f"Fehlende Angaben: {'; '.join(missing) or 'keine'}\n"
        f"Fehlende oder mangelhafte Fotos: {'; '.join(feedback) or 'keine'}\n"
        f"Link zum Hochladen: {link or 'keiner'}"
    )
    context = {
        "tenant": tenant.name if tenant else "",
        "customer": name,
        "plants": plants,
        "missing": missing,
        "feedback": feedback,
        "link": link,
    }
    resp, _ = ai.call(db, tenant_id, "follow_up", text, context=context, job_id=job_id)
    return str((resp.data or {}).get("message") or "").strip()


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


def _merge_plant(target: dict[str, Any], pa: dict[str, Any]) -> None:
    """Fill a draft plant with values from photo analysis where the message gave nothing (or less)."""
    for field in (
        "total_height_cm",
        "crown_width_cm",
        "pot_diameter_cm",
        "pot_height_cm",
        "weight_kg",
        "species",
        *knowledge.AI_TRAITS,
    ):
        new = pa.get(field) or {}
        old = target.get(field) or {"value": None, "confidence": 0}
        if new.get("value") is not None and (
            old.get("value") is None or new.get("confidence", 0) > old.get("confidence", 0)
        ):
            target[field] = new


def _merge_path(extracted: dict[str, Any], analysis_path: dict[str, Any]) -> None:
    path = extracted.get("path") or {}
    for k, new in analysis_path.items():
        if (
            k in path
            and new.get("value") is not None
            and (path[k].get("value") is None or new.get("confidence", 0) > path[k].get("confidence", 0))
        ):
            path[k] = new


def completeness(
    db: Session,
    tenant_id: uuid.UUID,
    photos: list[Photo],
    job_id: uuid.UUID | None = None,
    plant_names: list[str] | None = None,
) -> dict[str, Any]:
    resolver = SettingsResolver(db, tenant_id)
    required = list(resolver.get("photos.plant_set")) + list(resolver.get("photos.path_set"))
    required = [k for k in required if k != "path_segment"]
    labels = kind_labels()
    plant_names = plant_names or []
    context = {
        "photos": _photo_context(photos),
        "required_kinds": required,
        "kind_labels": labels,
        "plants": plant_names,
    }
    per_plant = any(_plant_no(p) for p in photos)
    text = (
        "Erwartete Fotoarten"
        + (" je Pflanze" if per_plant else "")
        + ": "
        + ", ".join(labels.get(k, k) for k in required)
        + "\n"
        + (
            "Pflanzen: " + "; ".join(f"Pflanze {i}: {n}" for i, n in enumerate(plant_names, start=1)) + "\n"
            if plant_names
            else ""
        )
        + "Lokale Bildprüfung (Schärfe, Belichtung, A4-Erkennung) je Foto:\n"
        + "\n".join(
            f"Bild {i}: {labels.get(p.kind, p.kind)}"
            + (f", Pflanze {_plant_no(p)}" if _plant_no(p) else "")
            + f"; scharf={p.quality.get('sharp')}; belichtung_ok={p.quality.get('exposure_ok')}; "
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
        p.ai_results = {**(p.ai_results or {}), "analysis": resp.data, "at": datetime.now(UTC).isoformat()}
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
    changed += apply_traits(plant, pa, threshold)
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


def _find_customer_by_address(
    db: Session, tenant_id: uuid.UUID, name: str, street: str, plz: str
) -> Customer | None:
    """Same name at the same address: the customer is known even without contact data."""
    return db.scalar(
        select(Customer)
        .join(Address, Address.customer_id == Customer.id)
        .where(
            Customer.tenant_id == tenant_id,
            Customer.deleted_at.is_(None),
            Address.deleted_at.is_(None),
            func.lower(Customer.name) == name.lower(),
            func.lower(Address.street) == street.lower(),
            Address.postal_code == plz,
        )
        .limit(1)
    )


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
    store_contact: bool | None = None,
) -> dict[str, Any]:
    """store_contact: take phone and e-mail into the customer (None = setting privacy.store_contact)."""
    from app.api.orders import create_path, create_plant, new_order

    if draft.status not in ("review", "new", "failed"):
        raise AppError("errors.draft_not_pending")
    tid = actor.require_tenant()
    resolver = SettingsResolver(db, tid)
    threshold = float(resolver.get("photos.min_confidence"))
    if store_contact is None:
        store_contact = _contact_wanted(resolver)
    data = extracted if extracted is not None else draft.extracted
    c, a, o = data.get("customer") or {}, data.get("address") or {}, data.get("order") or {}
    name = _value(c.get("name"))
    street, plz, city = _value(a.get("street")), _value(a.get("postal_code")), _value(a.get("city"))
    if not name or not street or not plz or not city:
        raise AppError("errors.validation")
    customer = _find_customer(db, tid, _value(c.get("email")), _value(c.get("phone")))
    if customer is None:
        customer = _find_customer_by_address(db, tid, name, street, plz)
    created_customer = customer is None
    if customer is None:
        customer = Customer(tenant_id=tid, name=name, source="ai_draft")
        db.add(customer)
    # contact data only if the owner wants it (setting or switch in the draft)
    for field in ("company", "email", "phone") if store_contact else ("company",):
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
    from app.models.notify import ShareLink

    for link in db.scalars(select(ShareLink).where(ShareLink.draft_id == draft.id)):
        if link.location:  # the customer shared the location through the customer link
            address.lat, address.lon = link.location["lat"], link.location["lon"]
            address.geocode_source = "customer"

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
    first_of_entry: dict[int, Plant] = {}  # plant number in the draft (1-based) -> first created plant
    for entry_no, p in enumerate(data.get("plants") or [], start=1):
        count = int(_value(p.get("count")) or 1)
        values = {
            "label": _value(p.get("label")),
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
            plant = create_plant(
                db, actor, order, vals, confidence=conf, path_id=path.id, traits=p, threshold=threshold
            )
            plants_created.append(plant)
            first_of_entry.setdefault(entry_no, plant)
    # move the photos from the draft to the order and to the plant the AI assigned them to
    # (or to the only plant)
    for photo in db.scalars(select(Photo).where(Photo.draft_id == draft.id)):
        photo.order_id = order.id
        if photo.kind.startswith("path"):
            photo.path_id = path.id
        elif _plant_no(photo) in first_of_entry:
            photo.plant_id = first_of_entry[_plant_no(photo)].id
        elif len(plants_created) == 1:
            photo.plant_id = plants_created[0].id
    draft.status = "confirmed"
    draft.confirmed_by = actor.user_id
    draft.confirmed_at = datetime.now(UTC)
    draft.customer_id = customer.id
    draft.order_id = order.id
    if extracted is not None:
        draft.extracted = extracted
    from app.models.notify import Notification

    for n in db.scalars(select(Notification).where(Notification.draft_id == draft.id)):
        n.order_id = order.id
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
    if resolver.get("ai.plant_images") != "off":
        from app.jobs.queue import enqueue

        enqueue(db, "ai.plant_images", {"order_id": str(order.id)}, tenant_id=tid, created_by=actor.user_id)
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

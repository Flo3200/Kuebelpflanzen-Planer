"""Vehicle drafts from cargo-space photos or a chat (package C).

Flow: photo or message -> AI (vehicle_photo / vehicle_chat) -> draft with {value, confidence} per
value, questions for missing or unsure values -> the owner answers in the chat or corrects values
(confidence 1) -> confirm creates or changes the vehicle, its cost settings and shelf modules.
Nothing is written to the vehicle before the confirmation; every confirmation is in the audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import service as ai
from app.ai.providers import AIImage
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.fleet.fields import COST_FIELDS, KINDS, LICENCES, REQUIRED, SHELF_FIELDS, VEHICLE_FIELDS
from app.fleet.layout import modules_of
from app.models.fleet import VehicleDraft, VehicleModule, VehicleModuleLink
from app.models.masterdata import Vehicle
from app.settings.service import SettingsResolver, set_value

FIELD_KINDS = dict(VEHICLE_FIELDS)


def _vf(value: Any, confidence: float = 1.0) -> dict[str, Any]:
    return {"value": value, "confidence": confidence if value is not None else 0.0}


def threshold(db: Session, tenant_id: uuid.UUID) -> float:
    return float(SettingsResolver(db, tenant_id).get("photos.min_confidence"))


def vehicle_data(db: Session, vehicle: Vehicle) -> dict[str, Any]:
    """Current values of a vehicle as a draft (confidence 1), the starting point for changes by chat."""
    r = SettingsResolver(db, vehicle.tenant_id)
    ch = ("vehicle", vehicle.id)
    shelves = [
        {
            "module_id": str(m.id),
            **{k: _vf(getattr(m, k)) for k, _ in SHELF_FIELDS},
        }
        for m in modules_of(db, vehicle.id)
        if m.kind == "shelf"
    ]
    return {
        "vehicle": {k: _vf(getattr(vehicle, k)) for k, _ in VEHICLE_FIELDS},
        "costs": {k: _vf(r.get(setting, ch)) for k, setting, _ in COST_FIELDS},
        "shelves": shelves,
    }


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only known keys, coerce types, check enums."""
    out: dict[str, Any] = {"vehicle": {}, "costs": {}, "shelves": []}
    for k, kind in VEHICLE_FIELDS:
        node = (data.get("vehicle") or {}).get(k) or {}
        out["vehicle"][k] = _coerce(node, kind, k)
    for k, _, kind in COST_FIELDS:
        out["costs"][k] = _coerce((data.get("costs") or {}).get(k) or {}, kind, k)
    for s in data.get("shelves") or []:
        shelf = {k: _coerce(s.get(k) or {}, kind, k) for k, kind in SHELF_FIELDS}
        if s.get("module_id"):
            shelf["module_id"] = str(s["module_id"])
        out["shelves"].append(shelf)
    return out


def _coerce(node: dict[str, Any], kind: str, key: str) -> dict[str, Any]:
    value, conf = node.get("value"), float(node.get("confidence") or 0)
    if value is None or value == "":
        return _vf(None)
    try:
        if kind == "number":
            value = round(float(str(value).replace(",", ".")), 2)
        elif kind == "integer":
            value = int(float(str(value).replace(",", ".")))
        elif kind == "boolean":
            value = value if isinstance(value, bool) else str(value).lower() in ("true", "ja", "1", "yes")
        else:
            value = str(value).strip()
    except (TypeError, ValueError):
        return _vf(None)
    if key == "kind" and value not in KINDS:
        return _vf(None)
    if key == "required_licence" and str(value).upper() not in LICENCES:
        return _vf(None)
    if key == "required_licence":
        value = str(value).upper()
    return {"value": value, "confidence": max(0.0, min(1.0, conf))}


def review_fields(data: dict[str, Any], limit: float) -> list[str]:
    out = []
    for section in ("vehicle", "costs"):
        for k, node in (data.get(section) or {}).items():
            if node.get("value") is not None and node.get("confidence", 0) < limit:
                out.append(f"{section}.{k}")
    out += [f"vehicle.{k}" for k in REQUIRED if (data.get("vehicle") or {}).get(k, {}).get("value") is None]
    for i, s in enumerate(data.get("shelves") or []):
        out += [
            f"shelves[{i}].{k}"
            for k, node in s.items()
            if isinstance(node, dict) and node.get("value") is not None and node.get("confidence", 0) < limit
        ]
    return sorted(set(out))


def _apply_result(db: Session, draft: VehicleDraft, result: dict[str, Any], model_label: str) -> None:
    data = _clean(result)
    # values a person set (confidence 1) are never overwritten by the AI
    for section in ("vehicle", "costs"):
        for k, node in (draft.data.get(section) or {}).items():
            if (
                node.get("confidence") == 1.0
                and node.get("value") is not None
                and draft.data.get("_edited", {}).get(f"{section}.{k}")
            ):
                data[section][k] = node
    data["_edited"] = draft.data.get("_edited", {})
    draft.data = data
    draft.questions = [str(q) for q in result.get("questions") or []][:5]
    limit = threshold(db, draft.tenant_id)
    draft.review_fields = review_fields(data, limit)
    draft.model = model_label
    reply = result.get("reply") or ""
    draft.messages = [
        *draft.messages,
        {
            "role": "assistant",
            "text": reply,
            "questions": draft.questions,
            "at": datetime.now(UTC).isoformat(),
        },
    ]


def _new_draft(db: Session, actor: Actor, source: str, vehicle_id: uuid.UUID | None) -> VehicleDraft:
    tid = actor.require_tenant()
    vehicle = None
    if vehicle_id is not None:
        vehicle = db.get(Vehicle, vehicle_id)
        if vehicle is None or vehicle.tenant_id != tid or vehicle.deleted_at is not None:
            raise NotFound()
    draft = VehicleDraft(
        tenant_id=tid,
        status="open",
        source=source,
        vehicle_id=vehicle.id if vehicle else None,
        data=vehicle_data(db, vehicle) if vehicle else {"vehicle": {}, "costs": {}, "shelves": []},
        messages=[],
        questions=[],
        review_fields=[],
        photo_file_ids=[],
        created_by=actor.user_id,
    )
    db.add(draft)
    db.flush()
    return draft


def chat(
    db: Session,
    actor: Actor,
    message: str,
    draft_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
) -> VehicleDraft:
    draft = get_open(db, actor, draft_id) if draft_id else _new_draft(db, actor, "chat", vehicle_id)
    draft.messages = [*draft.messages, {"role": "user", "text": message, "at": datetime.now(UTC).isoformat()}]
    history = "\n".join(
        f"{'Inhaber' if m['role'] == 'user' else 'KI'}: {m['text']}" for m in draft.messages[-12:]
    )
    import json

    text = (
        ("Änderung eines bestehenden Fahrzeugs.\n" if draft.vehicle_id else "Neues Fahrzeug.\n")
        + f"Bisheriger Entwurf (JSON): {json.dumps({k: v for k, v in draft.data.items() if not k.startswith('_')}, ensure_ascii=False)}\n\n"
        + f"Verlauf:\n{history}\n\nNeue Nachricht: {message}"
    )
    resp, model = ai.call(
        db,
        draft.tenant_id,
        "vehicle_chat",
        text,
        context={
            "draft": draft.data,
            "messages": draft.messages,
            "message": message,
            "threshold": threshold(db, draft.tenant_id),
        },
    )
    _apply_result(db, draft, resp.data or {}, model.label)
    db.flush()
    return draft


def from_photos(
    db: Session,
    actor: Actor,
    files: list[tuple[bytes, str]],
    note: str | None = None,
    vehicle_id: uuid.UUID | None = None,
) -> VehicleDraft:
    """Cargo-space photos (with an A4 sheet or a folding rule as scale) -> vehicle draft."""
    from app.ai.imagecheck import analyse
    from app.api.files import store_file
    from app.storage.backend import clean_image

    if not files:
        raise AppError("errors.validation")
    draft = _new_draft(db, actor, "photo", vehicle_id)
    images, photos = [], []
    for i, (raw, filename) in enumerate(files):
        try:
            clean, w, h = clean_image(raw)
        except Exception as exc:  # noqa: BLE001 - not an image
            raise AppError("errors.validation") from exc
        stored = store_file(
            db, actor, clean, filename or f"laderaum-{i + 1}.jpg", "image/jpeg", "vehicle_photo"
        )
        q = analyse(clean)
        draft.photo_file_ids = [*draft.photo_file_ids, {"file_id": str(stored.id), "width": w, "height": h}]
        images.append(AIImage(data=clean, label=f"Laderaum {i + 1}"))
        photos.append({"index": i + 1, "width": w, "height": h, "a4": q["a4"], "sharp": q["sharp"]})
    text = "Fotos des Laderaums:\n" + "\n".join(
        f"Bild {p['index']}: {p['width']}×{p['height']} px"
        + (
            f", A4-Maßstab {p['a4'].get('cm_per_px')} cm/px"
            if p["a4"].get("detected")
            else ", kein A4-Blatt erkannt"
        )
        for p in photos
    )
    if note:
        text += f"\n\nAngaben dazu: {note}"
        draft.messages = [{"role": "user", "text": note, "at": datetime.now(UTC).isoformat()}]
    resp, model = ai.call(
        db,
        draft.tenant_id,
        "vehicle_photo",
        text,
        images=images,
        context={"photos": photos, "note": note or "", "threshold": threshold(db, draft.tenant_id)},
    )
    _apply_result(db, draft, resp.data or {}, model.label)
    db.flush()
    return draft


def get_open(db: Session, actor: Actor, draft_id: uuid.UUID) -> VehicleDraft:
    draft = db.get(VehicleDraft, draft_id)
    if draft is None or draft.tenant_id != actor.tenant_id:
        raise NotFound()
    if draft.status != "open":
        raise AppError("errors.draft_not_pending", status_code=409)
    return draft


def correct(db: Session, actor: Actor, draft: VehicleDraft, data: dict[str, Any]) -> VehicleDraft:
    """Values entered by a person: confidence 1, never overwritten by the AI afterwards."""
    edited = dict(draft.data.get("_edited") or {})
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in draft.data.items()}
    for section in ("vehicle", "costs"):
        for k, node in (data.get(section) or {}).items():
            value = node.get("value") if isinstance(node, dict) else node
            merged.setdefault(section, {})[k] = {"value": value, "confidence": 1.0}
            edited[f"{section}.{k}"] = True
    if "shelves" in data:
        merged["shelves"] = [
            {
                **({"module_id": s["module_id"]} if s.get("module_id") else {}),
                **{
                    k: {
                        "value": (s.get(k) or {}).get("value") if isinstance(s.get(k), dict) else s.get(k),
                        "confidence": 1.0,
                    }
                    for k, _ in SHELF_FIELDS
                },
            }
            for s in data["shelves"]
        ]
    cleaned = _clean(merged)
    cleaned["_edited"] = edited
    draft.data = cleaned
    draft.review_fields = review_fields(cleaned, threshold(db, draft.tenant_id))
    db.flush()
    return draft


def confirm(db: Session, actor: Actor, draft: VehicleDraft) -> Vehicle:
    v = draft.data.get("vehicle") or {}
    missing = [k for k in REQUIRED if (v.get(k) or {}).get("value") is None]
    if missing:
        raise AppError("errors.vehicle_draft_incomplete", fields=", ".join(missing))
    created = draft.vehicle_id is None
    vehicle = Vehicle(tenant_id=draft.tenant_id) if created else db.get(Vehicle, draft.vehicle_id)
    if vehicle is None:
        raise NotFound()
    old = {k: getattr(vehicle, k, None) for k, _ in VEHICLE_FIELDS} if not created else {}
    changes: dict[str, Any] = {}
    for k, _ in VEHICLE_FIELDS:
        value = (v.get(k) or {}).get("value")
        if value is None:
            continue
        if getattr(vehicle, k, None) != value:
            changes[k] = value
            setattr(vehicle, k, value)
    if created:
        vehicle.name = vehicle.name or "Fahrzeug"
        vehicle.kind = vehicle.kind or "van"
        vehicle.required_licence = vehicle.required_licence or ("BE" if vehicle.kind == "trailer" else "B")
        db.add(vehicle)
    db.flush()
    # costs are object settings of the vehicle (hierarchy admin -> tenant -> vehicle, with audit)
    r = SettingsResolver(db, vehicle.tenant_id)
    for k, setting, _ in COST_FIELDS:
        value = ((draft.data.get("costs") or {}).get(k) or {}).get("value")
        if value is None:
            continue
        if created or float(r.get(setting, ("vehicle", vehicle.id))) != float(value):
            set_value(
                db,
                actor,
                scope="vehicle",
                key=setting,
                value=value,
                tenant_id=vehicle.tenant_id,
                object_id=vehicle.id,
            )
            changes[setting] = value
    changes.update(_apply_shelves(db, vehicle, draft.data.get("shelves") or [], created))
    audit.record(
        db,
        actor,
        tenant_id=vehicle.tenant_id,
        entity="vehicle",
        entity_id=vehicle.id,
        action="create" if created else "update",
        old={k: old.get(k) for k in changes if k in old} if not created else None,
        new={**changes, "source": f"vehicle_draft:{draft.source}", "draft_id": str(draft.id)},
    )
    draft.status = "confirmed"
    draft.confirmed_by = actor.user_id
    draft.confirmed_at = datetime.now(UTC)
    draft.result_vehicle_id = vehicle.id
    db.flush()
    from app.api.planning import mark_needs_replan

    mark_needs_replan(db, vehicle.tenant_id, f"vehicle:{vehicle.name}")
    return vehicle


def _apply_shelves(
    db: Session, vehicle: Vehicle, shelves: list[dict[str, Any]], created: bool
) -> dict[str, Any]:
    """Shelves of the draft become shelf modules of the vehicle. Modules shared with other vehicles
    are only unlinked, never changed; own modules are updated or removed (soft delete)."""
    current = {str(m.id): m for m in modules_of(db, vehicle.id) if m.kind == "shelf"}
    keep: set[str] = set()
    changed = 0
    for s in shelves:
        values = {k: (s.get(k) or {}).get("value") for k, _ in SHELF_FIELDS}
        mid = s.get("module_id")
        if mid and mid in current:
            keep.add(mid)
            module = current[mid]
            if _shared(db, module.id, vehicle.id):
                continue
            for k, val in values.items():
                if val is not None and getattr(module, k) != val:
                    setattr(module, k, val)
                    changed += 1
            continue
        module = VehicleModule(
            tenant_id=vehicle.tenant_id,
            kind="shelf",
            name=values.get("name") or f"Regal {vehicle.name}",
            x_cm=values.get("x_cm") or 0,
            y_cm=values.get("y_cm") or 0,
            length_cm=values.get("length_cm") or 120,
            depth_cm=values.get("depth_cm") or 40,
            height_cm=values.get("height_cm") or 90,
            clearance_cm=values.get("clearance_cm"),
            max_load_kg=values.get("max_load_kg"),
            blocks_floor=True,
            weight_kg=0,
        )
        db.add(module)
        db.flush()
        db.add(VehicleModuleLink(tenant_id=vehicle.tenant_id, vehicle_id=vehicle.id, module_id=module.id))
        changed += 1
    if not created:
        for mid, module in current.items():
            if mid in keep:
                continue
            link = db.scalar(
                select(VehicleModuleLink).where(
                    VehicleModuleLink.vehicle_id == vehicle.id, VehicleModuleLink.module_id == module.id
                )
            )
            if link is not None:
                db.delete(link)
            if not _shared(db, module.id, vehicle.id):
                module.deleted_at = datetime.now(UTC)
            changed += 1
    db.flush()
    return {"shelves": len(shelves)} if changed else {}


def _shared(db: Session, module_id: uuid.UUID, vehicle_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(VehicleModuleLink.id)
            .where(VehicleModuleLink.module_id == module_id, VehicleModuleLink.vehicle_id != vehicle_id)
            .limit(1)
        )
        is not None
    )


def draft_dict(d: VehicleDraft) -> dict[str, Any]:
    return {
        "id": d.id,
        "status": d.status,
        "source": d.source,
        "vehicle_id": d.vehicle_id,
        "data": {k: v for k, v in (d.data or {}).items() if not k.startswith("_")},
        "edited": sorted((d.data or {}).get("_edited", {})),
        "messages": d.messages,
        "questions": d.questions,
        "review_fields": d.review_fields,
        "photos": [f"/api/files/{p['file_id']}" for p in d.photo_file_ids or []],
        "model": d.model,
        "created_at": d.created_at,
        "confirmed_at": d.confirmed_at,
        "result_vehicle_id": d.result_vehicle_id,
    }

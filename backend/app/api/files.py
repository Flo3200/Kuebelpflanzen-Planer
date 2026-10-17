"""Photo upload (EXIF removed, local quality check), file download, photo listing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.imagecheck import analyse
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.models.orders import PHOTO_KINDS, Customer, Photo, PickupOrder, Plant, StoredFile
from app.settings.service import SettingsResolver
from app.storage.backend import IMAGE_TYPES, clean_image, get_storage, new_key, sha256

router = APIRouter(tags=["files"])


def store_file(
    db: Session, actor: Actor, data: bytes, filename: str, content_type: str, purpose: str
) -> StoredFile:
    tenant_id = actor.tenant_id
    ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}.get(content_type, "")
    key = new_key(tenant_id, purpose, ext)
    get_storage().put(key, data, content_type)
    row = StoredFile(
        tenant_id=tenant_id,
        key=key,
        filename=filename[:200],
        content_type=content_type,
        size=len(data),
        sha256=sha256(data),
        purpose=purpose,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    return row


def save_photo(
    db: Session,
    actor: Actor,
    raw: bytes,
    filename: str,
    kind: str,
    *,
    order_id: uuid.UUID | None = None,
    plant_id: uuid.UUID | None = None,
    path_id: uuid.UUID | None = None,
    segment_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
    stop_id: uuid.UUID | None = None,
    position: int = 0,
    caption: str | None = None,
) -> Photo:
    try:
        clean, width, height = clean_image(raw)
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for broken files
        raise AppError("errors.file_type") from exc
    stored = store_file(db, actor, clean, filename.rsplit(".", 1)[0] + ".jpg", "image/jpeg", "photo")
    quality = analyse(clean)
    photo = Photo(
        tenant_id=actor.tenant_id,
        file_id=stored.id,
        kind=kind if kind in PHOTO_KINDS else "other",
        order_id=order_id,
        plant_id=plant_id,
        path_id=path_id,
        segment_id=segment_id,
        draft_id=draft_id,
        stop_id=stop_id,
        position=position,
        width_px=width,
        height_px=height,
        quality={k: v for k, v in quality.items() if k != "a4"},
        a4=quality["a4"],
        a4_detected=bool(quality["a4"].get("detected")),
        caption=caption,
    )
    db.add(photo)
    db.flush()
    return photo


def photo_dict(p: Photo) -> dict[str, Any]:
    return {
        "id": p.id,
        "file_id": p.file_id,
        "url": f"/api/files/{p.file_id}",
        "kind": p.kind,
        "order_id": p.order_id,
        "plant_id": p.plant_id,
        "path_id": p.path_id,
        "segment_id": p.segment_id,
        "draft_id": p.draft_id,
        "stop_id": p.stop_id,
        "position": p.position,
        "width": p.width_px,
        "height": p.height_px,
        "quality": p.quality,
        "a4": p.a4,
        "a4_detected": p.a4_detected,
        "ai_results": p.ai_results,
        "caption": p.caption,
        "created_at": p.created_at,
    }


def _ensure_consent(db: Session, actor: Actor, order_id: uuid.UUID | None, confirm: bool) -> None:
    if order_id is None:
        return
    order = db.get(PickupOrder, order_id)
    if order is None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    customer = db.get(Customer, order.customer_id)
    if customer is None or customer.consent_photos:
        return
    if not confirm:
        raise AppError("errors.consent_missing", status_code=409)
    text = SettingsResolver(db, actor.tenant_id).get("privacy.consent_text")
    customer.consent_photos = True
    customer.consent_at = datetime.now(UTC)
    customer.consent_text = text or "(mündlich/schriftlich bestätigt)"
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="customer",
        entity_id=customer.id,
        action="consent",
        new={"consent_photos": True},
    )


@router.post("/api/photos", status_code=201)
async def upload_photo(
    actor: CurrentActor,
    db: DB,
    file: UploadFile = File(...),
    kind: str = Form("other"),
    order_id: uuid.UUID | None = Form(None),
    plant_id: uuid.UUID | None = Form(None),
    path_id: uuid.UUID | None = Form(None),
    segment_id: uuid.UUID | None = Form(None),
    draft_id: uuid.UUID | None = Form(None),
    stop_id: uuid.UUID | None = Form(None),
    position: int = Form(0),
    caption: str | None = Form(None),
    consent_confirmed: bool = Form(False),
) -> dict[str, Any]:
    actor.require_tenant()
    if not (actor.has("orders.write") or actor.has("drafts.write") or actor.has("driver.app")):
        actor.require("orders.write")
    if file.content_type not in IMAGE_TYPES:
        raise AppError("errors.file_type")
    raw = await file.read()
    if len(raw) > get_config().max_upload_mb * 1024 * 1024:
        raise AppError("errors.file_too_large", status_code=413)
    if plant_id is not None and order_id is None:
        plant = db.get(Plant, plant_id)
        if plant is None or plant.tenant_id != actor.tenant_id:
            raise NotFound()
        order_id = plant.order_id
    if draft_id is None and stop_id is None:
        _ensure_consent(db, actor, order_id, consent_confirmed)
    photo = save_photo(
        db,
        actor,
        raw,
        file.filename or "foto.jpg",
        kind,
        order_id=order_id,
        plant_id=plant_id,
        path_id=path_id,
        segment_id=segment_id,
        draft_id=draft_id,
        stop_id=stop_id,
        position=position,
        caption=caption,
    )
    return photo_dict(photo)


@router.get("/api/photos")
def list_photos(
    actor: CurrentActor,
    db: DB,
    order_id: uuid.UUID | None = None,
    plant_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
    stop_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    actor.require_tenant()
    stmt = select(Photo).where(Photo.tenant_id == actor.tenant_id)
    if order_id:
        stmt = stmt.where(Photo.order_id == order_id)
    if plant_id:
        stmt = stmt.where(Photo.plant_id == plant_id)
    if draft_id:
        stmt = stmt.where(Photo.draft_id == draft_id)
    if stop_id:
        stmt = stmt.where(Photo.stop_id == stop_id)
    if not any((order_id, plant_id, draft_id, stop_id)):
        raise AppError("errors.validation")
    return [photo_dict(p) for p in db.scalars(stmt.order_by(Photo.kind, Photo.position, Photo.created_at))]


@router.patch("/api/photos/{photo_id}")
def update_photo(photo_id: uuid.UUID, data: dict[str, Any], actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    photo = db.get(Photo, photo_id)
    if photo is None or photo.tenant_id != actor.tenant_id:
        raise NotFound()
    for key in ("kind", "plant_id", "path_id", "segment_id", "position", "caption"):
        if key in data:
            value = data[key]
            if key.endswith("_id") and value:
                value = uuid.UUID(str(value))
            setattr(photo, key, value)
    return photo_dict(photo)


@router.delete("/api/photos/{photo_id}")
def delete_photo(photo_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    photo = db.get(Photo, photo_id)
    if photo is None or photo.tenant_id != actor.tenant_id:
        raise NotFound()
    stored = db.get(StoredFile, photo.file_id)
    db.delete(photo)
    if stored is not None:
        get_storage().delete(stored.key)
        db.delete(stored)
    audit.record(db, actor, tenant_id=actor.tenant_id, entity="photo", entity_id=photo_id, action="delete")
    return {"ok": True}


@router.get("/api/files/{file_id}")
def get_file(file_id: uuid.UUID, actor: CurrentActor, db: DB, download: bool = False) -> Response:
    stored = db.get(StoredFile, file_id)
    if stored is None or (actor.tenant_id is not None and stored.tenant_id != actor.tenant_id):
        raise NotFound()
    try:
        data = get_storage().get(stored.key)
    except FileNotFoundError as exc:
        raise NotFound() from exc
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type=stored.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{stored.filename}"',
            "Cache-Control": "private, max-age=86400",
        },
    )

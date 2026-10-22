"""Draft inbox: forwarded messages become drafts; humans review, correct and confirm them."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import intake
from app.api.deps import DB, CurrentActor
from app.api.files import photo_dict, save_photo
from app.core import audit
from app.core.config import get_config
from app.core.errors import AppError, NotFound
from app.jobs.queue import enqueue, run_now
from app.models.orders import Draft, Photo
from app.storage.backend import IMAGE_TYPES

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def draft_dict(d: Draft, photos: list[Photo] | None = None) -> dict[str, Any]:
    return {
        "id": d.id,
        "status": d.status,
        "source_kind": d.source_kind,
        "source_text": d.source_text,
        "extracted": d.extracted,
        "confidence": d.confidence,
        "review_fields": d.review_fields,
        "photo_check": d.photo_check,
        "follow_up": d.follow_up,
        "model": d.model,
        "job_id": d.job_id,
        "created_at": d.created_at,
        "created_via": d.created_via,
        "confirmed_at": d.confirmed_at,
        "customer_id": d.customer_id,
        "order_id": d.order_id,
        "error": d.error,
        "photos": [photo_dict(p) for p in photos] if photos is not None else None,
        "summary": _summary(d),
    }


def _notification(db, d: Draft) -> dict[str, Any] | None:
    from app.models.notify import Notification
    from app.notify.service import notification_dict

    n = db.scalar(
        select(Notification)
        .where(Notification.draft_id == d.id, Notification.kind == "photos_missing")
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    return notification_dict(n) if n else None


def _summary(d: Draft) -> str:
    ex = d.extracted or {}
    name = ((ex.get("customer") or {}).get("name") or {}).get("value")
    city = ((ex.get("address") or {}).get("city") or {}).get("value")
    plants = sum(int(((p.get("count") or {}).get("value")) or 1) for p in ex.get("plants") or [])
    bits = [b for b in (name, city, f"{plants} Pflanzen" if plants else None) if b]
    return " · ".join(bits) or (d.source_text or "")[:80]


def _get(db, actor, draft_id: uuid.UUID) -> Draft:
    d = db.get(Draft, draft_id)
    if d is None or d.tenant_id != actor.tenant_id:
        raise NotFound()
    return d


@router.post("", status_code=201)
async def create_draft(
    actor: CurrentActor,
    db: DB,
    text: str = Form(""),
    source_kind: str = Form("text"),
    files: list[UploadFile] = File(default=[]),
    kinds: list[str] = Form(default=[]),
    sync: bool = Form(False),
) -> dict[str, Any]:
    """Paste or forward a message (text, e-mail content, voice message as text) with photos."""
    actor.require("drafts.write")
    tid = actor.require_tenant()
    if not text.strip() and not files:
        raise AppError("errors.validation")
    draft = Draft(
        tenant_id=tid,
        source_kind=source_kind if source_kind in ("text", "email", "voice", "agent", "form") else "text",
        source_text=text,
        created_by=actor.user_id,
        created_via=actor.via,
        status="processing",
    )
    db.add(draft)
    db.flush()
    max_bytes = get_config().max_upload_mb * 1024 * 1024
    for i, f in enumerate(files):
        if f.content_type not in IMAGE_TYPES:
            raise AppError("errors.file_type")
        raw = await f.read()
        if len(raw) > max_bytes:
            raise AppError("errors.file_too_large", status_code=413)
        kind = kinds[i] if i < len(kinds) and kinds[i] not in ("", "auto") else None
        photo = save_photo(
            db, actor, raw, f.filename or f"foto{i}.jpg", kind or "other", draft_id=draft.id, position=i
        )
        if kind is None:
            photo.ai_results = {"auto": True}  # the AI decides kind and plant (ai.photo_sort)
    job = enqueue(
        db, "ai.process_draft", {"draft_id": str(draft.id)}, tenant_id=tid, created_by=actor.user_id
    )
    draft.job_id = job.id
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="draft",
        entity_id=draft.id,
        action="create",
        new={"photos": len(files)},
    )
    if sync:
        run_now(db, job)
        db.refresh(draft)
    photos = list(db.scalars(select(Photo).where(Photo.draft_id == draft.id).order_by(Photo.position)))
    return draft_dict(draft, photos)


@router.get("")
def list_drafts(actor: CurrentActor, db: DB, status: str | None = None) -> list[dict[str, Any]]:
    actor.require("drafts.write")
    stmt = select(Draft).where(Draft.tenant_id == actor.require_tenant())
    if status:
        stmt = stmt.where(Draft.status.in_(status.split(",")))
    return [draft_dict(d) for d in db.scalars(stmt.order_by(Draft.created_at.desc()).limit(300))]


@router.get("/{draft_id}")
def get_draft(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("drafts.write")
    d = _get(db, actor, draft_id)
    photos = list(db.scalars(select(Photo).where(Photo.draft_id == d.id).order_by(Photo.position)))
    from app.settings.service import SettingsResolver

    return {
        **draft_dict(d, photos),
        "notification": _notification(db, d),
        "store_contact_default": bool(SettingsResolver(db, d.tenant_id).get("privacy.store_contact")),
    }


class DraftPatch(BaseModel):
    extracted: dict[str, Any] | None = None
    follow_up: str | None = None


@router.patch("/{draft_id}")
def patch_draft(draft_id: uuid.UUID, data: DraftPatch, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("drafts.write")
    d = _get(db, actor, draft_id)
    if d.status not in ("review", "failed", "new"):
        raise AppError("errors.draft_not_pending")
    if data.extracted is not None:
        d.extracted = data.extracted
        d.confidence = intake.flatten_confidence(data.extracted)
    if data.follow_up is not None:
        d.follow_up = data.follow_up
    return draft_dict(d)


class ConfirmIn(BaseModel):
    extracted: dict[str, Any] | None = None
    order_status: str = "confirmed"
    store_contact: bool | None = None  # None: setting privacy.store_contact


@router.post("/{draft_id}/confirm")
def confirm(draft_id: uuid.UUID, data: ConfirmIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Turn the (corrected) draft into customer, address, order, plants and path."""
    actor.require("drafts.write", "orders.write", "customers.write")
    d = _get(db, actor, draft_id)
    status = data.order_status if data.order_status in ("draft", "confirmed") else "confirmed"
    return intake.confirm_draft(
        db, actor, d, data.extracted, order_status=status, store_contact=data.store_contact
    )


@router.post("/{draft_id}/reject")
def reject(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("drafts.write")
    d = _get(db, actor, draft_id)
    d.status = "rejected"
    from app.notify.service import close_for_draft

    close_for_draft(db, d.id)
    audit.record(db, actor, tenant_id=d.tenant_id, entity="draft", entity_id=d.id, action="reject")
    return draft_dict(d)


@router.post("/{draft_id}/reprocess")
def reprocess(draft_id: uuid.UUID, actor: CurrentActor, db: DB, sync: bool = False) -> dict[str, Any]:
    actor.require("drafts.write")
    d = _get(db, actor, draft_id)
    if d.status == "confirmed":
        raise AppError("errors.draft_not_pending")
    d.status = "processing"
    job = enqueue(
        db, "ai.process_draft", {"draft_id": str(d.id)}, tenant_id=d.tenant_id, created_by=actor.user_id
    )
    d.job_id = job.id
    if sync:
        run_now(db, job)
        db.refresh(d)
    return draft_dict(d)

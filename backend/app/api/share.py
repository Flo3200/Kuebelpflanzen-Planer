"""Customer link (module "share"): a personal link without an account. The customer uploads photos
and shares the location; they go straight into the draft (the AI evaluates again) or the order.

Public endpoints under /api/share/<token>; staff endpoints create links for drafts and orders."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentActor
from app.api.files import save_photo
from app.core import audit
from app.core.config import get_config
from app.core.context import system_actor
from app.core.db import system_session
from app.core.errors import AppError, NotFound
from app.core.modules import require_module
from app.i18n import t
from app.jobs.queue import enqueue
from app.models.core import Tenant
from app.models.notify import ShareLink
from app.models.orders import Address, Draft, Photo, PickupOrder
from app.notify.service import create_share_link, find_share_link, notify
from app.settings.service import SettingsResolver
from app.storage.backend import IMAGE_TYPES

router = APIRouter(tags=["share"])
public_router = APIRouter(tags=["share"])

MAX_UPLOADS = 60


def _link(db, token: str) -> ShareLink:
    row = find_share_link(db, token)
    if row is None:
        raise AppError("errors.share_link_invalid", status_code=404)
    require_module(db, row.tenant_id, "share")
    return row


def _needed(db, row: ShareLink) -> list[str]:
    """What the AI still misses (feedback of the photo check), shown to the customer as a checklist."""
    if row.draft_id:
        d = db.get(Draft, row.draft_id)
        if d is not None and d.status != "confirmed":
            missing = [m for m in (d.extracted or {}).get("missing") or [] if "kontakt" not in m.lower()]
            return list((d.photo_check or {}).get("feedback") or []) + missing
    order = _order_of(db, row)
    if order is not None:
        return list(((order.estimate or {}).get("photo_check") or {}).get("feedback") or [])
    return []


def _order_of(db, row: ShareLink) -> PickupOrder | None:
    if row.order_id:
        return db.get(PickupOrder, row.order_id)
    if row.draft_id:
        d = db.get(Draft, row.draft_id)
        if d is not None and d.order_id:
            return db.get(PickupOrder, d.order_id)
    return None


@public_router.get("/api/share/{token}")
def view(token: str) -> dict[str, Any]:
    with system_session() as db:
        row = _link(db, token)
        tenant = db.get(Tenant, row.tenant_id)
        r = SettingsResolver(db, row.tenant_id)
        row.last_used_at = datetime.now(UTC)
        return {
            "tenant": tenant.name if tenant else "",
            "needed": _needed(db, row),
            "uploads": row.uploads,
            "consent_given": row.consent_at is not None,
            "consent_text": r.get("privacy.consent_text") or t("share.default_consent"),
            "location": row.location or None,
            "expires_at": row.expires_at,
        }


class ConsentIn(BaseModel):
    accept: bool


@public_router.post("/api/share/{token}/consent")
def consent(token: str, data: ConsentIn) -> dict[str, Any]:
    with system_session() as db:
        row = _link(db, token)
        row.consent_at = datetime.now(UTC) if data.accept else None
        return {"consent_given": row.consent_at is not None}


@public_router.post("/api/share/{token}/photos", status_code=201)
async def upload(token: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    max_bytes = get_config().max_upload_mb * 1024 * 1024
    raws = []
    for f in files:
        if f.content_type not in IMAGE_TYPES:
            raise AppError("errors.file_type")
        raw = await f.read()
        if len(raw) > max_bytes:
            raise AppError("errors.file_too_large", status_code=413)
        raws.append((f.filename or "foto.jpg", raw))
    with system_session() as db:
        row = _link(db, token)
        if row.consent_at is None:
            raise AppError("errors.consent_required", status_code=409)
        if row.uploads + len(raws) > MAX_UPLOADS:
            raise AppError("errors.validation")
        actor = system_actor(row.tenant_id, label="Kunden-Link").with_via("share_link")
        order = _order_of(db, row)
        draft = db.get(Draft, row.draft_id) if row.draft_id else None
        start = (
            db.scalar(
                select(Photo.position)
                .where(Photo.draft_id == row.draft_id)
                .order_by(Photo.position.desc())
                .limit(1)
            )
            if draft
            else 0
        )
        for i, (name, raw) in enumerate(raws, start=1):
            if draft is not None and draft.status != "confirmed":
                photo = save_photo(
                    db, actor, raw, name, "other", draft_id=draft.id, position=(start or 0) + i
                )
                photo.ai_results = {"auto": True}
            elif order is not None:
                save_photo(db, actor, raw, name, "other", order_id=order.return_of_id or order.id)
        row.uploads += len(raws)
        row.last_used_at = datetime.now(UTC)
        _after_customer_input(db, row, draft, order, photos=len(raws))
        return {"uploads": row.uploads, "received": len(raws)}


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    note: str | None = Field(default=None, max_length=1000)


@public_router.put("/api/share/{token}/location")
def location(token: str, data: LocationIn) -> dict[str, Any]:
    with system_session() as db:
        row = _link(db, token)
        row.location = {
            "lat": data.lat,
            "lon": data.lon,
            "accuracy_m": data.accuracy_m,
            "at": datetime.now(UTC).isoformat(),
        }
        if data.note:
            row.note = data.note.strip()
        order = _order_of(db, row)
        draft = db.get(Draft, row.draft_id) if row.draft_id else None
        if order is not None:
            apply_location(db, row, order)
        _after_customer_input(db, row, draft if order is None else None, order, photos=0, located=True)
        return {"location": row.location}


def apply_location(db, row: ShareLink, order: PickupOrder) -> None:
    """The customer's pin becomes the address coordinates (like the portal)."""
    a = db.get(Address, order.address_id)
    if a is None or not row.location:
        return
    a.lat, a.lon = row.location["lat"], row.location["lon"]
    a.geocode_source = "customer"
    if row.note and not a.access_notes:
        a.access_notes = row.note
    audit.record(
        db,
        system_actor(row.tenant_id, label="Kunden-Link"),
        tenant_id=row.tenant_id,
        entity="address",
        entity_id=a.id,
        action="update",
        new={"lat": a.lat, "lon": a.lon, "source": "customer_link"},
    )


def _after_customer_input(db, row, draft, order, photos: int, located: bool = False) -> None:
    """AI evaluates again; the office gets a notification."""
    if draft is not None and draft.status in ("review", "failed", "new") and photos:
        draft.status = "processing"
        job = enqueue(db, "ai.process_draft", {"draft_id": str(draft.id)}, tenant_id=row.tenant_id)
        draft.job_id = job.id
    elif order is not None and photos:
        enqueue(
            db,
            "ai.check_order_photos",
            {"order_id": str(order.return_of_id or order.id)},
            tenant_id=row.tenant_id,
        )
    who = ""
    if draft is not None:
        who = (((draft.extracted or {}).get("customer") or {}).get("name") or {}).get("value") or ""
    if order is not None and not who:
        who = order.number
    notify(
        db,
        row.tenant_id,
        "customer_upload",
        t("notifications.customer_upload", who=who or "Kunde"),
        body=t(
            "notifications.customer_upload_body",
            n=photos,
            loc=t("notifications.with_location") if located or row.location else "",
        ),
        link=f"/betrieb/posteingang/{draft.id}"
        if draft is not None
        else f"/betrieb/auftraege/{order.id}"
        if order
        else None,
        draft_id=draft.id if draft is not None else None,
        order_id=order.id if order is not None else None,
        data={"photos": photos, "location": row.location or None},
    )


# ---------------------------------------------------------------------------- staff side


@router.post("/api/drafts/{draft_id}/share-link")
def draft_link(draft_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("drafts.write")
    tid = actor.require_tenant()
    require_module(db, tid, "share")
    d = db.get(Draft, draft_id)
    if d is None or d.tenant_id != tid:
        raise NotFound()
    row, url = create_share_link(db, tid, draft_id=d.id)
    return {"url": url, "expires_at": row.expires_at}


@router.post("/api/orders/{order_id}/share-link")
def order_link(order_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("orders.write")
    tid = actor.require_tenant()
    require_module(db, tid, "share")
    o = db.get(PickupOrder, order_id)
    if o is None or o.tenant_id != tid:
        raise NotFound()
    row, url = create_share_link(db, tid, order_id=o.id)
    return {"url": url, "expires_at": row.expires_at}

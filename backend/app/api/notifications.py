"""Notifications for the office (bell in the top bar): missing photos with a ready message for the
customer, uploads through the customer link, tours ended early, spontaneous teams."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentActor
from app.core.errors import NotFound
from app.models.notify import Notification
from app.notify.service import notification_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(actor: CurrentActor, db: DB, include_done: bool = False) -> dict[str, Any]:
    actor.require("tenant.view")
    tid = actor.require_tenant()
    q = select(Notification).where(Notification.tenant_id == tid)
    if not include_done:
        q = q.where(Notification.done_at.is_(None))
    rows = list(db.scalars(q.order_by(Notification.updated_at.desc()).limit(100)))
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.tenant_id == tid, Notification.read_at.is_(None), Notification.done_at.is_(None))
    )
    return {"items": [notification_dict(n) for n in rows], "unread": int(unread or 0)}


def _get(db, actor, notification_id: uuid.UUID) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.tenant_id != actor.tenant_id:
        raise NotFound()
    return n


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.view")
    n = _get(db, actor, notification_id)
    n.read_at = n.read_at or datetime.now(UTC)
    return notification_dict(n)


@router.post("/{notification_id}/done")
def mark_done(notification_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Done = handled (e.g. the message was sent to the customer); disappears from the list."""
    actor.require("tenant.view")
    n = _get(db, actor, notification_id)
    now = datetime.now(UTC)
    n.read_at = n.read_at or now
    n.done_at = now
    return notification_dict(n)


@router.post("/read-all")
def read_all(actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.view")
    now = datetime.now(UTC)
    count = 0
    for n in db.scalars(
        select(Notification).where(
            Notification.tenant_id == actor.require_tenant(), Notification.read_at.is_(None)
        )
    ):
        n.read_at = now
        count += 1
    return {"read": count}

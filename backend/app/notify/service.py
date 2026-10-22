"""Notifications for the office and customer share links (photos and location without an account)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.modules import module_enabled
from app.core.security import new_token, token_hash
from app.models.notify import Notification, ShareLink
from app.settings.service import SettingsResolver


def notify(
    db: Session,
    tenant_id: uuid.UUID,
    kind: str,
    title: str,
    *,
    body: str | None = None,
    message: str | None = None,
    link: str | None = None,
    draft_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    replace_open: bool = True,
) -> Notification:
    """Create a notification. An open one of the same kind for the same draft/order is updated instead,
    so reprocessing a draft does not pile up messages."""
    row = None
    if replace_open and (draft_id or order_id):
        q = select(Notification).where(
            Notification.tenant_id == tenant_id, Notification.kind == kind, Notification.done_at.is_(None)
        )
        q = (
            q.where(Notification.draft_id == draft_id)
            if draft_id
            else q.where(Notification.order_id == order_id)
        )
        row = db.scalar(q.limit(1))
    if row is None:
        row = Notification(tenant_id=tenant_id, kind=kind, draft_id=draft_id, order_id=order_id)
        db.add(row)
    row.title = title[:200]
    row.body = body
    row.message = message
    row.link = link
    row.data = data or {}
    row.read_at = None
    db.flush()
    return row


def close_for_draft(db: Session, draft_id: uuid.UUID, kind: str | None = None) -> None:
    q = select(Notification).where(Notification.draft_id == draft_id, Notification.done_at.is_(None))
    if kind:
        q = q.where(Notification.kind == kind)
    now = datetime.now(UTC)
    for n in db.scalars(q):
        n.done_at = now
        n.read_at = n.read_at or now


def notification_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "message": n.message,
        "link": n.link,
        "draft_id": n.draft_id,
        "order_id": n.order_id,
        "data": n.data,
        "read": n.read_at is not None,
        "done": n.done_at is not None,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


# ------------------------------------------------------------------------- share links


def share_url(token: str) -> str:
    return f"{get_config().base_url.rstrip('/')}/teilen/{token}"


def create_share_link(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    draft_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
) -> tuple[ShareLink, str]:
    """New personal link for a draft or order. Returns the row and the URL (the token is not stored)."""
    days = int(SettingsResolver(db, tenant_id).get("share.link_days"))
    token = new_token(24)
    row = ShareLink(
        tenant_id=tenant_id,
        token_hash=token_hash(token),
        draft_id=draft_id,
        order_id=order_id,
        expires_at=datetime.now(UTC) + timedelta(days=days),
        uploads=0,
        location={},
    )
    db.add(row)
    db.flush()
    return row, share_url(token)


def share_enabled(db: Session, tenant_id: uuid.UUID) -> bool:
    return module_enabled(db, tenant_id, "share")


def find_share_link(db: Session, token: str) -> ShareLink | None:
    row = db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash(token)))
    if row is None or row.revoked or row.expires_at < datetime.now(UTC):
        return None
    return row

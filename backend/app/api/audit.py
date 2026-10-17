"""Change log with undo."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.crud import undo_entity_update
from app.api.deps import DB, CurrentActor
from app.core import audit as audit_mod
from app.core.errors import AppError, NotFound
from app.models.core import AuditLog
from app.settings import service as settings_service

router = APIRouter(prefix="/api/audit", tags=["audit"])


def entry_dict(e: AuditLog) -> dict[str, Any]:
    return {
        "id": e.id,
        "tenant_id": e.tenant_id,
        "actor_label": e.actor_label,
        "actor_user_id": e.actor_user_id,
        "via": e.via,
        "entity": e.entity,
        "entity_id": e.entity_id,
        "action": e.action,
        "old_value": e.old_value,
        "new_value": e.new_value,
        "batch_id": e.batch_id,
        "undoable": e.undoable and e.undone_by is None,
        "undone": e.undone_by is not None,
        "created_at": e.created_at,
    }


@router.get("")
def list_entries(
    actor: CurrentActor,
    db: DB,
    entity: str | None = None,
    entity_id: str | None = None,
    via: str | None = None,
    tenant_id: uuid.UUID | None = None,
    platform_only: bool = False,
    limit: int = Query(100, le=1000),
    offset: int = 0,
) -> dict[str, Any]:
    actor.require("audit.read")
    stmt = select(AuditLog)
    if actor.tenant_id is not None:
        stmt = stmt.where(AuditLog.tenant_id == actor.tenant_id)
    elif platform_only:
        stmt = stmt.where(AuditLog.tenant_id.is_(None))
    elif tenant_id is not None:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id.like(f"%{entity_id}%"))
    if via:
        stmt = stmt.where(AuditLog.via == via)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))
    return {"total": total, "items": [entry_dict(e) for e in rows]}


@router.post("/batch/{batch_id}/undo")
def undo_batch(batch_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    first = db.scalar(select(AuditLog).where(AuditLog.batch_id == batch_id).limit(1))
    if first is None or (actor.tenant_id is not None and first.tenant_id != actor.tenant_id):
        raise NotFound()
    return undo(first.id, actor, db)


@router.post("/{entry_id}/undo")
def undo(entry_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    entry = db.get(AuditLog, entry_id)
    if entry is None or (actor.tenant_id is not None and entry.tenant_id != actor.tenant_id):
        raise NotFound()
    if entry.entity == "setting":
        count = settings_service.undo(db, actor, entry_id)
        return {"ok": True, "count": count}
    if entry.action == "update" and entry.undoable and entry.undone_by is None:
        undo_entity_update(db, actor, entry)
        log = audit_mod.record(
            db,
            actor,
            tenant_id=entry.tenant_id,
            entity=entry.entity,
            entity_id=entry.entity_id,
            action="undo",
            old=entry.new_value,
            new=entry.old_value,
        )
        db.flush()
        entry.undone_by = log.id
        return {"ok": True, "count": 1}
    raise AppError("errors.not_undoable")

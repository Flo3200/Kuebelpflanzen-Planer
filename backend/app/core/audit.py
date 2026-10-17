"""Change log helpers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.context import Actor
from app.models.core import AuditLog


def record(
    db: Session,
    actor: Actor,
    *,
    tenant_id: uuid.UUID | None,
    entity: str,
    entity_id: str | uuid.UUID | None,
    action: str,
    old: Any = None,
    new: Any = None,
    batch_id: uuid.UUID | None = None,
    undoable: bool = False,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor.user_id,
        actor_label=actor.label,
        via=actor.via,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        action=action,
        old_value=_jsonable(old),
        new_value=_jsonable(new),
        batch_id=batch_id,
        undoable=undoable,
    )
    db.add(entry)
    return entry


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)

"""Resolution, validation, writing, resetting and undoing of settings.

Resolution order (most specific wins):
  objects in the given chain (tenant row before global row for each object)
  -> tenant -> platform -> registry default
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, Forbidden, NotFound
from app.models.core import AuditLog, SettingValue
from app.settings.registry import GROUPS, OBJECT_SCOPES, REGISTRY, SettingDef, get_def

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Which permission allows writing object-level settings of a scope.
OBJECT_WRITE_PERMISSION = {
    "staff": "staff.write",
    "vehicle": "fleet.write",
    "equipment": "fleet.write",
    "species": "platform.species",  # knowledge base, admin only
    "plant": "orders.write",
    "customer": "customers.write",
    "tour": "planning.write",
}

ChainItem = tuple[str, uuid.UUID]


@dataclass(frozen=True)
class Resolved:
    key: str
    value: Any
    origin: str  # default | platform | tenant | <object scope>
    origin_object_id: uuid.UUID | None = None
    origin_is_global: bool = False  # object value set by the admin for a global object (species)


# ---------------------------------------------------------------- validation


def coerce(defn: SettingDef, raw: Any) -> Any:
    """Convert and check a raw value. Raises AppError with a translation key."""
    try:
        if defn.type == "int":
            if isinstance(raw, bool):
                raise ValueError
            value: Any = int(raw) if not isinstance(raw, float) or raw.is_integer() else None
            if value is None:
                raise ValueError
        elif defn.type == "float":
            if isinstance(raw, bool):
                raise ValueError
            value = float(str(raw).replace(",", ".")) if isinstance(raw, str) else float(raw)
        elif defn.type == "bool":
            if isinstance(raw, bool):
                value = raw
            elif isinstance(raw, str) and raw.lower() in ("true", "1", "ja", "yes", "on"):
                value = True
            elif isinstance(raw, str) and raw.lower() in ("false", "0", "nein", "no", "off"):
                value = False
            else:
                raise ValueError
        elif defn.type in ("str", "text"):
            value = "" if raw is None else str(raw)
            if len(value) > (20000 if defn.type == "text" else 500):
                raise AppError("errors.setting_too_long", key=defn.key)
        elif defn.type == "enum":
            value = str(raw)
            if defn.choices and value not in defn.choices:
                raise AppError("errors.setting_choice", key=defn.key, choices=", ".join(defn.choices))
        elif defn.type == "time":
            value = str(raw)
            if not _TIME_RE.match(value):
                raise AppError("errors.setting_time", key=defn.key)
        elif defn.type == "json":
            if not isinstance(raw, (dict, list)):
                raise ValueError
            value = raw
        else:  # pragma: no cover - registry is static
            raise AppError("errors.setting_type", key=defn.key)
    except AppError:
        raise
    except (TypeError, ValueError) as exc:
        raise AppError("errors.setting_type", key=defn.key, type=defn.type) from exc

    if defn.type in ("int", "float"):
        if defn.min is not None and value < defn.min:
            raise AppError("errors.setting_min", key=defn.key, min=defn.min)
        if defn.max is not None and value > defn.max:
            raise AppError("errors.setting_max", key=defn.key, max=defn.max)
    return value


# ---------------------------------------------------------------- resolver


class SettingsResolver:
    """Loads platform and tenant values once; object values on demand (batched)."""

    def __init__(self, db: Session, tenant_id: uuid.UUID | None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._platform: dict[str, Any] = {}
        self._tenant: dict[str, Any] = {}
        # (scope, object_id) -> key -> (value, is_global)
        self._objects: dict[tuple[str, uuid.UUID], dict[str, tuple[Any, bool]]] = {}
        self._loaded_objects: set[tuple[str, uuid.UUID]] = set()

        cond = SettingValue.scope == "platform"
        if tenant_id is not None:
            cond = or_(cond, and_(SettingValue.scope == "tenant", SettingValue.tenant_id == tenant_id))
        for row in db.scalars(select(SettingValue).where(cond)):
            if row.scope == "platform":
                self._platform[row.key] = row.value
            else:
                self._tenant[row.key] = row.value

    def prefetch(self, scope: str, ids: Iterable[uuid.UUID]) -> None:
        wanted = [i for i in set(ids) if (scope, i) not in self._loaded_objects]
        if not wanted:
            return
        tenant_cond = SettingValue.tenant_id.is_(None)
        if self.tenant_id is not None:
            tenant_cond = or_(tenant_cond, SettingValue.tenant_id == self.tenant_id)
        rows = self.db.scalars(
            select(SettingValue).where(
                SettingValue.scope == scope, SettingValue.object_id.in_(wanted), tenant_cond
            )
        )
        for oid in wanted:
            self._loaded_objects.add((scope, oid))
            self._objects.setdefault((scope, oid), {})
        for row in rows:
            bucket = self._objects[(scope, row.object_id)]
            is_global = row.tenant_id is None
            # a tenant-specific value beats the admin's value on a global object
            if row.key in bucket and not bucket[row.key][1] and is_global:
                continue
            bucket[row.key] = (row.value, is_global)

    def resolve(self, key: str, *chain: ChainItem | None) -> Resolved:
        defn = get_def(key)
        for item in chain:
            if item is None or item[1] is None:
                continue
            scope, oid = item
            if scope not in defn.levels:
                continue
            self.prefetch(scope, [oid])
            hit = self._objects.get((scope, oid), {}).get(key)
            if hit is not None:
                return Resolved(key, hit[0], scope, oid, hit[1])
        if "tenant" in defn.levels and key in self._tenant:
            return Resolved(key, self._tenant[key], "tenant")
        if "platform" in defn.levels and key in self._platform:
            return Resolved(key, self._platform[key], "platform")
        return Resolved(key, defn.default, "default")

    def get(self, key: str, *chain: ChainItem | None) -> Any:
        return self.resolve(key, *chain).value

    def platform_value(self, key: str) -> Any:
        return self._platform.get(key, get_def(key).default)


# ---------------------------------------------------------------- writing


def _check_write(actor: Actor, defn: SettingDef, scope: str, tenant_id: uuid.UUID | None) -> None:
    if scope not in defn.levels:
        raise AppError("errors.setting_level", key=defn.key, level=scope)
    if scope == "platform":
        actor.require("platform.settings")
        if tenant_id is not None:
            raise AppError("errors.setting_level", key=defn.key, level=scope)
        return
    if tenant_id is None and not (scope in OBJECT_SCOPES and actor.is_platform_admin):
        raise AppError("errors.tenant_required")
    if actor.is_platform_admin:
        return
    if actor.tenant_id != tenant_id:
        raise Forbidden()
    if defn.admin_only:
        raise Forbidden("errors.setting_admin_only", key=defn.key)
    if scope == "tenant":
        actor.require("tenant.settings")
    else:
        actor.require(OBJECT_WRITE_PERMISSION.get(scope, "tenant.settings"))


def _find(db: Session, scope: str, tenant_id, object_id, key) -> SettingValue | None:
    return db.scalar(
        select(SettingValue).where(
            SettingValue.scope == scope,
            SettingValue.tenant_id.is_(None) if tenant_id is None else SettingValue.tenant_id == tenant_id,
            SettingValue.object_id.is_(None) if object_id is None else SettingValue.object_id == object_id,
            SettingValue.key == key,
        )
    )


def _entity_id(scope: str, object_id, key: str) -> str:
    return f"{scope}:{object_id or ''}:{key}"


def set_value(
    db: Session,
    actor: Actor,
    *,
    scope: str,
    key: str,
    value: Any,
    tenant_id: uuid.UUID | None = None,
    object_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> AuditLog:
    """Write one override; returns the audit entry (its id allows a one-click undo)."""
    defn = get_def(key)
    if scope in OBJECT_SCOPES and object_id is None:
        raise AppError("errors.object_required")
    if scope in ("platform", "tenant") and object_id is not None:
        raise AppError("errors.setting_level", key=key, level=scope)
    _check_write(actor, defn, scope, tenant_id)
    clean = coerce(defn, value)
    row = _find(db, scope, tenant_id, object_id, key)
    old = None if row is None else {"value": row.value}
    if row is None:
        row = SettingValue(scope=scope, tenant_id=tenant_id, object_id=object_id, key=key, value=clean)
        db.add(row)
    else:
        row.value = clean
    row.updated_by = actor.user_id
    entry = audit.record(
        db,
        actor,
        tenant_id=tenant_id,
        entity="setting",
        entity_id=_entity_id(scope, object_id, key),
        action="set",
        old=old,
        new={"value": clean},
        batch_id=batch_id,
        undoable=True,
    )
    db.flush()
    return entry


def reset(
    db: Session,
    actor: Actor,
    *,
    scope: str,
    tenant_id: uuid.UUID | None = None,
    object_id: uuid.UUID | None = None,
    key: str | None = None,
    group: str | None = None,
    all_scopes: bool = False,
) -> tuple[uuid.UUID, int]:
    """Delete overrides. Granularity: one key, one group, one object/level, or a whole tenant
    (all_scopes=True removes tenant and all object values of the tenant). Returns (batch_id, count)."""
    if group is not None and group not in GROUPS:
        raise NotFound("errors.unknown_group", group=group)
    query = select(SettingValue)
    if tenant_id is None:
        query = query.where(SettingValue.tenant_id.is_(None))
    else:
        query = query.where(SettingValue.tenant_id == tenant_id)
    if not all_scopes:
        query = query.where(SettingValue.scope == scope)
        if object_id is None:
            query = query.where(SettingValue.object_id.is_(None))
        else:
            query = query.where(SettingValue.object_id == object_id)
    if key is not None:
        query = query.where(SettingValue.key == key)
    rows = [
        r
        for r in db.scalars(query)
        if r.key in REGISTRY and (group is None or REGISTRY[r.key].group == group)
    ]
    batch_id = uuid.uuid4()
    for row in rows:
        _check_write(actor, REGISTRY[row.key], row.scope, row.tenant_id)
        audit.record(
            db,
            actor,
            tenant_id=row.tenant_id,
            entity="setting",
            entity_id=_entity_id(row.scope, row.object_id, row.key),
            action="reset",
            old={"value": row.value},
            new=None,
            batch_id=batch_id,
            undoable=True,
        )
        db.delete(row)
    db.flush()
    return batch_id, len(rows)


def _parse_entity_id(entity_id: str) -> tuple[str, uuid.UUID | None, str]:
    scope, oid, key = entity_id.split(":", 2)
    return scope, (uuid.UUID(oid) if oid else None), key


def undo(db: Session, actor: Actor, audit_id: uuid.UUID) -> int:
    """Undo one log entry or – if it belongs to a batch – the whole batch. Returns number of changes."""
    entry = db.get(AuditLog, audit_id)
    if entry is None:
        raise NotFound()
    if not entry.undoable or entry.undone_by is not None:
        raise AppError("errors.not_undoable")
    if entry.batch_id is not None:
        entries = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.batch_id == entry.batch_id)
                .order_by(AuditLog.created_at.desc())
            )
        )
    else:
        entries = [entry]
    undo_batch = uuid.uuid4()
    count = 0
    for e in entries:
        if e.entity != "setting" or e.undone_by is not None:
            continue
        scope, object_id, key = _parse_entity_id(e.entity_id or "")
        defn = get_def(key)
        _check_write(actor, defn, scope, e.tenant_id)
        row = _find(db, scope, e.tenant_id, object_id, key)
        current = None if row is None else {"value": row.value}
        if current != e.new_value:
            raise AppError("errors.undo_conflict", key=key)
        if e.old_value is None:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = SettingValue(scope=scope, tenant_id=e.tenant_id, object_id=object_id, key=key)
                db.add(row)
            row.value = e.old_value["value"]
            row.updated_by = actor.user_id
        log = audit.record(
            db,
            actor,
            tenant_id=e.tenant_id,
            entity="setting",
            entity_id=e.entity_id,
            action="undo",
            old=current,
            new=e.old_value,
            batch_id=undo_batch,
            undoable=False,
        )
        db.flush()
        e.undone_by = log.id
        count += 1
    db.flush()
    return count


# ---------------------------------------------------------------- listing


def describe(
    resolver: SettingsResolver,
    scope: str,
    chain: list[ChainItem] | None = None,
    keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolved values for a level, with origin and the value inherited from above."""
    from app.settings.texts import setting_text

    out = []
    for key, defn in REGISTRY.items():
        if scope not in defn.levels or (keys is not None and key not in keys):
            continue
        chain = chain or []
        here = resolver.resolve(key, *chain)
        if scope == "platform":
            parent = Resolved(key, defn.default, "default")
            own = here if here.origin == "platform" else None
        elif scope == "tenant":
            own = here if here.origin == "tenant" else None
            parent = resolver.resolve(key) if own is None else _without_tenant(resolver, key)
        else:
            own = here if (here.origin == scope and chain and here.origin_object_id == chain[0][1]) else None
            parent = resolver.resolve(key, *chain[1:]) if own is not None else here
        texts = setting_text(key)
        out.append(
            {
                "key": key,
                "group": defn.group,
                "type": defn.type,
                "unit": defn.unit,
                "min": defn.min,
                "max": defn.max,
                "choices": list(defn.choices) if defn.choices else None,
                "choices_source": defn.choices_source,
                "important": defn.important,
                "admin_only": defn.admin_only,
                "module": defn.module,
                "label": texts["label"],
                "help": texts["help"],
                "value": here.value,
                "origin": here.origin,
                "origin_is_global": here.origin_is_global,
                "overridden_here": own is not None,
                "inherited_value": parent.value,
                "inherited_origin": parent.origin,
                "default": defn.default,
            }
        )
    return out


def _without_tenant(resolver: SettingsResolver, key: str) -> Resolved:
    defn = get_def(key)
    if "platform" in defn.levels and key in resolver._platform:
        return Resolved(key, resolver._platform[key], "platform")
    return Resolved(key, defn.default, "default")

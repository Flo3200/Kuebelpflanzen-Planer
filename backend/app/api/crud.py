"""Generic CRUD routers and field metadata generated from SQLAlchemy models.

Column metadata (``info``) understood here:
  hidden    – never exposed (tenant_id, deleted_at)
  readonly  – exposed but not writable
  required  – required on create even if nullable in the database
  unit, group, enum, fk (target entity), help, widget, min, max
"""

import datetime as dt
import enum
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text, Time, Uuid, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql.schema import Column

from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.context import Actor
from app.core.errors import AppError, NotFound
from app.i18n import catalog

ENTITIES: dict[str, "EntitySpec"] = {}


class EntitySpec:
    def __init__(
        self,
        name: str,
        model: type,
        read_perm: str,
        write_perm: str,
        search: tuple[str, ...] = (),
        filters: tuple[str, ...] = (),
        order_by: tuple[str, ...] = ("created_at",),
        settings_scope: str | None = None,
        exclude: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.model = model
        self.read_perm = read_perm
        self.write_perm = write_perm
        self.search = search
        self.filters = filters
        self.order_by = order_by
        self.settings_scope = settings_scope
        self.exclude = exclude

    @property
    def columns(self) -> list[Column]:
        return [c for c in self.model.__table__.columns if c.name not in self.exclude]

    def writable(self) -> list[Column]:
        return [
            c
            for c in self.columns
            if c.name not in ("id", "tenant_id", "created_at", "updated_at", "deleted_at")
            and not c.info.get("hidden")
            and not c.info.get("readonly")
        ]

    def visible(self) -> list[Column]:
        return [c for c in self.columns if not c.info.get("hidden")]


def py_type(col: Column) -> Any:
    t = col.type
    if isinstance(t, Uuid):
        return uuid.UUID
    if isinstance(t, Boolean):
        return bool
    if isinstance(t, Integer):
        return int
    if isinstance(t, (Float, Numeric)):
        return float
    if isinstance(t, DateTime):
        return dt.datetime
    if isinstance(t, Date):
        return dt.date
    if isinstance(t, Time):
        return dt.time
    if isinstance(t, (String, Text)):
        return str
    if isinstance(t, JSONB):
        return Any
    return Any


def type_name(col: Column) -> str:
    t = py_type(col)
    if col.info.get("enum"):
        return "enum"
    if col.info.get("widget"):
        return col.info["widget"]
    return {
        uuid.UUID: "uuid",
        bool: "bool",
        int: "int",
        float: "float",
        dt.datetime: "datetime",
        dt.date: "date",
        dt.time: "time",
        str: "text" if isinstance(col.type, Text) else "str",
    }.get(t, "json")


def _has_default(col: Column) -> bool:
    return col.default is not None or col.server_default is not None


def build_schemas(spec: EntitySpec) -> tuple[type[BaseModel], type[BaseModel], type[BaseModel]]:
    create_fields: dict[str, Any] = {}
    update_fields: dict[str, Any] = {}
    for col in spec.writable():
        t = py_type(col)
        if col.info.get("enum"):
            t = enum.Enum(f"{spec.name}_{col.name}", {v: v for v in col.info["enum"]}, type=str)  # type: ignore[misc]
        required = col.info.get("required") or (
            not col.nullable and not _has_default(col) and not col.info.get("optional")
        )
        if required:
            create_fields[col.name] = (t, ...)
        else:
            create_fields[col.name] = (t | None, None)
        update_fields[col.name] = (t | None, None)
    read_fields: dict[str, Any] = {c.name: (py_type(c) | None, None) for c in spec.visible()}
    cfg = ConfigDict(from_attributes=True, use_enum_values=True)
    create = create_model(f"{spec.name}_create", __config__=cfg, **create_fields)
    update = create_model(f"{spec.name}_update", __config__=cfg, **update_fields)
    read = create_model(f"{spec.name}_read", __config__=cfg, **read_fields)
    return create, update, read


def row_dict(spec: EntitySpec, row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.key if hasattr(c, "key") else c.name) for c in spec.visible()}


def _jsonable_diff(spec: EntitySpec, row: Any, names: list[str]) -> dict[str, Any]:
    return {n: getattr(row, n) for n in names}


def _model_for_table(name: str) -> Any:
    from app.models.base import Base

    for mapper in Base.registry.mappers:
        if getattr(mapper.class_, "__tablename__", None) == name:
            return mapper.class_
    return None


def check_foreign_keys(db: Session, spec: EntitySpec, values: dict[str, Any]) -> None:
    """Referenced rows must be visible to the current tenant (FK constraints ignore RLS)."""
    for col in spec.writable():
        value = values.get(col.name)
        if value is None or not col.foreign_keys:
            continue
        target = _model_for_table(next(iter(col.foreign_keys)).column.table.name)
        if target is None:
            continue
        ref = db.get(target, value)
        if ref is None or getattr(ref, "deleted_at", None) is not None:
            raise AppError("errors.validation")


def get_row(db: Session, spec: EntitySpec, actor: Actor, row_id: uuid.UUID) -> Any:
    row = db.get(spec.model, row_id)
    if row is None or getattr(row, "deleted_at", None) is not None:
        raise NotFound()
    tid = getattr(row, "tenant_id", None)
    if tid is not None and actor.tenant_id is not None and tid != actor.tenant_id:
        raise NotFound()
    return row


def apply_values(spec: EntitySpec, row: Any, values: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    changes: dict[str, tuple[Any, Any]] = {}
    allowed = {c.name for c in spec.writable()}
    for key, value in values.items():
        if key not in allowed:
            continue
        old = getattr(row, key)
        if old != value:
            changes[key] = (old, value)
            setattr(row, key, value)
    return changes


def crud_router(
    spec: EntitySpec,
    prefix: str,
    *,
    before_save: Callable[[Session, Actor, Any, bool], None] | None = None,
    after_save: Callable[[Session, Actor, Any, bool], None] | None = None,
    extra_filters: Callable[[Any, dict[str, Any]], Any] | None = None,
) -> APIRouter:
    ENTITIES[spec.name] = spec
    Create, Update, Read = build_schemas(spec)
    router = APIRouter(prefix=prefix, tags=[spec.name])
    model = spec.model

    @router.get("", response_model=list[Read], name=f"list_{spec.name}")
    def list_rows(
        actor: CurrentActor,
        db: DB,
        q: str | None = Query(None, description="Volltextsuche"),
        limit: int = Query(500, le=5000),
        offset: int = 0,
        filter: list[str] = Query(default=[], description="feld=wert"),
    ) -> list[Any]:
        actor.require(spec.read_perm)
        stmt = select(model)
        if hasattr(model, "deleted_at"):
            stmt = stmt.where(model.deleted_at.is_(None))
        if hasattr(model, "tenant_id") and actor.tenant_id is not None:
            stmt = stmt.where(model.tenant_id == actor.tenant_id)
        if q and spec.search:
            stmt = stmt.where(or_(*[getattr(model, f).ilike(f"%{q}%") for f in spec.search]))
        parsed: dict[str, Any] = {}
        for f in filter:
            if "=" in f:
                k, v = f.split("=", 1)
                if k in spec.filters:
                    parsed[k] = v
                    col = getattr(model, k)
                    stmt = stmt.where(col.is_(None) if v == "null" else col == v)
        if extra_filters:
            stmt = extra_filters(stmt, parsed)
        for o in spec.order_by:
            desc = o.startswith("-")
            col = getattr(model, o.lstrip("-"))
            stmt = stmt.order_by(col.desc() if desc else col)
        return list(db.scalars(stmt.offset(offset).limit(limit)))

    @router.get("/{row_id}", response_model=Read, name=f"get_{spec.name}")
    def get_one(row_id: uuid.UUID, actor: CurrentActor, db: DB) -> Any:
        actor.require(spec.read_perm)
        return get_row(db, spec, actor, row_id)

    @router.post("", response_model=Read, status_code=201, name=f"create_{spec.name}")
    def create(data: Create, actor: CurrentActor, db: DB) -> Any:  # type: ignore[valid-type]
        actor.require(spec.write_perm)
        row = model()
        if hasattr(model, "tenant_id"):
            row.tenant_id = actor.require_tenant()
        values = data.model_dump()  # type: ignore[attr-defined]
        check_foreign_keys(db, spec, values)
        apply_values(spec, row, values)
        if before_save:
            before_save(db, actor, row, True)
        db.add(row)
        db.flush()
        audit.record(
            db,
            actor,
            tenant_id=getattr(row, "tenant_id", None),
            entity=spec.name,
            entity_id=row.id,
            action="create",
            new=row_dict(spec, row),
        )
        if after_save:
            after_save(db, actor, row, True)
        db.flush()
        db.refresh(row)
        return row

    @router.patch("/{row_id}", response_model=Read, name=f"update_{spec.name}")
    def update(row_id: uuid.UUID, data: Update, actor: CurrentActor, db: DB) -> Any:  # type: ignore[valid-type]
        actor.require(spec.write_perm)
        row = get_row(db, spec, actor, row_id)
        values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
        check_foreign_keys(db, spec, values)
        changes = apply_values(spec, row, values)
        if before_save:
            before_save(db, actor, row, False)
        if changes:
            audit.record(
                db,
                actor,
                tenant_id=getattr(row, "tenant_id", None),
                entity=spec.name,
                entity_id=row.id,
                action="update",
                old={k: v[0] for k, v in changes.items()},
                new={k: v[1] for k, v in changes.items()},
                undoable=True,
            )
        if after_save:
            after_save(db, actor, row, False)
        db.flush()
        db.refresh(row)
        return row

    @router.delete("/{row_id}", name=f"delete_{spec.name}")
    def delete(row_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict:
        actor.require(spec.write_perm)
        from app.agents.confirm import confirm_if_agent

        confirm_if_agent(db, actor, f"delete:{spec.name}", {"id": str(row_id)})
        row = get_row(db, spec, actor, row_id)
        audit.record(
            db,
            actor,
            tenant_id=getattr(row, "tenant_id", None),
            entity=spec.name,
            entity_id=row.id,
            action="delete",
            old=row_dict(spec, row),
        )
        if hasattr(row, "deleted_at"):
            row.deleted_at = dt.datetime.now(dt.UTC)
        else:
            db.delete(row)
        return {"ok": True}

    return router


def undo_entity_update(db: Session, actor: Actor, entry: Any) -> None:
    spec = ENTITIES.get(entry.entity)
    if spec is None:
        raise AppError("errors.not_undoable")
    actor.require(spec.write_perm)
    row = get_row(db, spec, actor, uuid.UUID(entry.entity_id))
    for key, new in (entry.new_value or {}).items():
        current = audit._jsonable(getattr(row, key))
        if current != new:
            raise AppError("errors.undo_conflict", key=key)
    for key, old in (entry.old_value or {}).items():
        col = spec.model.__table__.columns[key]
        t = py_type(col)
        if old is not None and t is uuid.UUID:
            old = uuid.UUID(old)
        elif old is not None and t is dt.datetime:
            old = dt.datetime.fromisoformat(old)
        elif old is not None and t is dt.date:
            old = dt.date.fromisoformat(old)
        elif old is not None and t is dt.time:
            old = dt.time.fromisoformat(old)
        setattr(row, key, old)


def field_meta(spec: EntitySpec, lang: str = "de") -> list[dict[str, Any]]:
    labels = catalog(lang).get("fields", {})
    ent = labels.get(spec.name, {})
    common = labels.get("_common", {})
    out = []
    writable = {c.name for c in spec.writable()}
    for col in spec.visible():
        entry = ent.get(col.name) or common.get(col.name) or {}
        if isinstance(entry, str):
            entry = {"label": entry}
        out.append(
            {
                "name": col.name,
                "type": type_name(col),
                "nullable": col.nullable,
                "required": bool(
                    col.info.get("required")
                    or (not col.nullable and not _has_default(col) and not col.info.get("optional"))
                ),
                "writable": col.name in writable,
                "unit": col.info.get("unit"),
                "group": col.info.get("group"),
                "enum": col.info.get("enum"),
                "enum_labels": {
                    v: catalog(lang).get("enums", {}).get(f"{spec.name}.{col.name}.{v}")
                    or catalog(lang).get("enums", {}).get(v, v)
                    for v in (col.info.get("enum") or [])
                },
                "fk": col.info.get("fk"),
                "options": col.info.get("enum_values"),
                "min": col.info.get("min"),
                "max": col.info.get("max"),
                "list": col.info.get("list", False),
                "label": entry.get("label", col.name),
                "help": entry.get("help", ""),
            }
        )
    return out

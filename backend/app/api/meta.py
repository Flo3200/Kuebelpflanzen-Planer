"""Metadata for generated forms: entity fields, health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.crud import ENTITIES, field_meta
from app.api.deps import CurrentActor
from app.core.db import system_session
from app.core.errors import NotFound

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/entities")
def entities(actor: CurrentActor) -> list[str]:
    return sorted(ENTITIES)


@router.get("/entities/{name}")
def entity_fields(name: str, actor: CurrentActor) -> dict[str, Any]:
    spec = ENTITIES.get(name)
    if spec is None:
        raise NotFound()
    return {"name": name, "settings_scope": spec.settings_scope, "fields": field_meta(spec)}


health_router = APIRouter(tags=["meta"])


@health_router.get("/api/health")
def health() -> dict[str, Any]:
    with system_session() as db:
        db.execute(text("SELECT 1"))
    return {"ok": True}

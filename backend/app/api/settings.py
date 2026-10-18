"""Settings API: registry, resolved values with origin, override, reset."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.confirm import confirm_if_agent
from app.api.deps import DB, CurrentActor
from app.core.context import Actor
from app.core.errors import AppError, Forbidden
from app.i18n import catalog
from app.settings.chains import chain_for
from app.settings.registry import GROUPS, OBJECT_SCOPES, SETTINGS
from app.settings.service import SettingsResolver, describe, reset, set_value
from app.settings.texts import choice_label, group_label, setting_text

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SetIn(BaseModel):
    scope: str
    key: str
    value: Any
    object_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None


class ResetIn(BaseModel):
    scope: str
    object_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    key: str | None = None
    group: str | None = None
    all_scopes: bool = False


def target_tenant(actor: Actor, requested: uuid.UUID | None, scope: str) -> uuid.UUID | None:
    """Tenant whose values are addressed. Tenant users always address their own tenant."""
    if scope == "platform":
        return None
    if actor.is_platform_admin and actor.tenant_id is None:
        return requested  # admin in platform view: explicit tenant or global object (species)
    if requested is not None and requested != actor.tenant_id:
        raise Forbidden()
    return actor.tenant_id


def registry_payload(lang: str = "de") -> dict[str, Any]:
    return {
        "groups": [{"key": g, "label": group_label(g, lang)} for g in GROUPS],
        "settings": [
            {
                "key": s.key,
                "type": s.type,
                "unit": s.unit,
                "default": s.default,
                "min": s.min,
                "max": s.max,
                "choices": list(s.choices) if s.choices else None,
                "choice_labels": {c: choice_label(s.key, c, lang) for c in (s.choices or ())},
                "choices_source": s.choices_source,
                "levels": list(s.levels),
                "group": s.group,
                "important": s.important,
                "admin_only": s.admin_only,
                **setting_text(s.key, lang),
            }
            for s in SETTINGS
        ],
        "origins": catalog(lang).get("origins", {}),
    }


@router.get("/registry")
def get_registry() -> dict[str, Any]:
    """Alle Einstellungen mit Typ, Einheit, Standard, Grenzen, Ebenen und Erklärung."""
    return registry_payload()


def values_for(
    db: Session, actor: Actor, scope: str, object_id: uuid.UUID | None, tenant_id: uuid.UUID | None
):
    if scope not in ("platform", "tenant", *OBJECT_SCOPES):
        raise AppError("errors.setting_level", key="*", level=scope)
    if scope == "platform":
        actor.require("platform.settings")
    if scope in OBJECT_SCOPES and object_id is None:
        raise AppError("errors.object_required")
    resolver = SettingsResolver(db, tenant_id)
    chain = chain_for(db, scope, object_id) if object_id else []
    return describe(resolver, scope, chain)


@router.get("")
def get_values(
    actor: CurrentActor,
    db: DB,
    scope: str = "tenant",
    object_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Aufgelöste Werte einer Ebene mit Herkunft („geerbt vom Admin“ usw.)."""
    tid = target_tenant(actor, tenant_id, scope)
    if scope == "tenant" and tid is None:
        raise AppError("errors.tenant_required")
    return {
        "scope": scope,
        "object_id": object_id,
        "tenant_id": tid,
        "groups": [{"key": g, "label": group_label(g)} for g in GROUPS],
        "values": values_for(db, actor, scope, object_id, tid),
    }


BILLING_RELEVANT = {"ai.key_mode", "ai.monthly_limit_eur", "platform.mode"}


@router.put("")
def put_value(data: SetIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    tid = target_tenant(actor, data.tenant_id, data.scope)
    if data.key.startswith("billing.") or data.key in BILLING_RELEVANT:
        # agents: billing-relevant changes need a human confirmation
        confirm_if_agent(
            db,
            actor,
            f"setting:{data.key}",
            {
                "key": data.key,
                "value": data.value,
                "scope": data.scope,
                "tenant_id": str(tid) if tid else None,
                "object_id": str(data.object_id) if data.object_id else None,
            },
        )
    entry = set_value(
        db, actor, scope=data.scope, key=data.key, value=data.value, tenant_id=tid, object_id=data.object_id
    )
    _after_change(db, [data.key], tid)
    return {"ok": True, "key": data.key, "value": entry.new_value["value"], "audit_id": entry.id}


@router.post("/reset")
def post_reset(data: ResetIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Zurücksetzen: einzelner Wert (key), Gruppe (group), ganzes Objekt/Ebene, ganzer Betrieb (all_scopes)."""
    tid = target_tenant(actor, data.tenant_id, data.scope)
    if data.all_scopes and tid is None:
        raise AppError("errors.tenant_required")
    batch_id, count = reset(
        db,
        actor,
        scope=data.scope,
        tenant_id=tid,
        object_id=data.object_id,
        key=data.key,
        group=data.group,
        all_scopes=data.all_scopes,
    )
    _after_change(db, [data.key] if data.key else None, tid, data.group)
    return {"ok": True, "batch_id": batch_id, "count": count}


def _after_change(
    db: Session, keys: list[str] | None, tenant_id: uuid.UUID | None, group: str | None = None
) -> None:
    """Settings that influence estimates trigger a recomputation of the affected tenant(s)."""
    from app.settings.registry import REGISTRY
    from app.timemodel.service import ESTIMATE_GROUPS, schedule_refresh

    groups = (
        {REGISTRY[k].group for k in keys if k in REGISTRY}
        if keys
        else ({group} if group else set(ESTIMATE_GROUPS))
    )
    if groups & ESTIMATE_GROUPS:
        schedule_refresh(db, tenant_id)

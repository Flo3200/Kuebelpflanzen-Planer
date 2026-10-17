"""AI administration (providers, models, prices, prompts, usage, evaluation) and tenant AI features."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai.functions import FUNCTIONS
from app.ai.service import prompt_for, spend_status
from app.api.deps import DB, CurrentActor
from app.api.files import store_file
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.security import encrypt
from app.jobs.queue import enqueue, run_now
from app.models.ai import (
    AIModel,
    AIProvider,
    AIUsage,
    EvalItem,
    EvalRun,
    EvalSet,
    PromptTemplate,
    TenantAIKey,
)
from app.models.core import Tenant
from app.models.orders import PickupOrder
from app.settings.service import SettingsResolver
from app.storage.backend import clean_image

router = APIRouter(tags=["ai"])


def provider_dict(p: AIProvider) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind,
        "base_url": p.base_url,
        "active": p.active,
        "has_key": bool(p.api_key_enc),
    }


def model_dict(m: AIModel, provider: AIProvider | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "provider_id": m.provider_id,
        "provider_name": provider.name if provider else None,
        "provider_kind": provider.kind if provider else None,
        "model_name": m.model_name,
        "label": m.label,
        "input_price_per_mtok": m.input_price_per_mtok,
        "output_price_per_mtok": m.output_price_per_mtok,
        "price_currency": m.price_currency,
        "supports_vision": m.supports_vision,
        "supports_tools": m.supports_tools,
        "max_output_tokens": m.max_output_tokens,
        "is_default": m.is_default,
        "use_fallbacks": m.use_fallbacks,
        "effort": m.effort,
        "active": m.active,
    }


# ------------------------------------------------------------------------------ admin: providers/models


class ProviderIn(BaseModel):
    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    active: bool | None = None
    api_key: str | None = None


@router.get("/api/admin/ai/providers")
def list_providers(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("platform.ai")
    return [provider_dict(p) for p in db.scalars(select(AIProvider).order_by(AIProvider.name))]


@router.post("/api/admin/ai/providers", status_code=201)
def create_provider(data: ProviderIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    if not data.name or data.kind not in ("anthropic", "openai", "openai_compatible", "fake"):
        raise AppError("errors.validation")
    p = AIProvider(
        name=data.name,
        kind=data.kind,
        base_url=data.base_url,
        active=data.active if data.active is not None else True,
    )
    if data.api_key:
        p.api_key_enc = encrypt(data.api_key)
    db.add(p)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=None,
        entity="ai_provider",
        entity_id=p.id,
        action="create",
        new={"name": p.name, "kind": p.kind},
    )
    return provider_dict(p)


@router.patch("/api/admin/ai/providers/{provider_id}")
def update_provider(provider_id: uuid.UUID, data: ProviderIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    p = db.get(AIProvider, provider_id)
    if p is None:
        raise NotFound()
    values = data.model_dump(exclude_unset=True)
    key = values.pop("api_key", None)
    for k, v in values.items():
        setattr(p, k, v)
    if key is not None:
        p.api_key_enc = encrypt(key) if key else None
    audit.record(
        db,
        actor,
        tenant_id=None,
        entity="ai_provider",
        entity_id=p.id,
        action="update",
        new={**values, **({"api_key": "(geändert)"} if key is not None else {})},
    )
    return provider_dict(p)


class ModelIn(BaseModel):
    provider_id: uuid.UUID | None = None
    model_name: str | None = None
    label: str | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    price_currency: str | None = None
    supports_vision: bool | None = None
    supports_tools: bool | None = None
    max_output_tokens: int | None = None
    is_default: bool | None = None
    use_fallbacks: bool | None = None
    effort: str | None = None
    active: bool | None = None


@router.get("/api/admin/ai/models")
def admin_models(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("platform.ai")
    providers = {p.id: p for p in db.scalars(select(AIProvider))}
    return [
        model_dict(m, providers.get(m.provider_id))
        for m in db.scalars(select(AIModel).order_by(AIModel.label))
    ]


@router.post("/api/admin/ai/models", status_code=201)
def create_model(data: ModelIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    if not data.provider_id or not data.model_name:
        raise AppError("errors.validation")
    values = data.model_dump(exclude_unset=True)
    values.setdefault("label", data.model_name)
    m = AIModel(**values)
    db.add(m)
    db.flush()
    if m.is_default:
        _single_default(db, m)
    audit.record(
        db, actor, tenant_id=None, entity="ai_model", entity_id=m.id, action="create", new=model_dict(m)
    )
    return model_dict(m, db.get(AIProvider, m.provider_id))


def _single_default(db, keep: AIModel) -> None:
    for other in db.scalars(select(AIModel).where(AIModel.is_default.is_(True), AIModel.id != keep.id)):
        other.is_default = False


@router.patch("/api/admin/ai/models/{model_id}")
def update_model(model_id: uuid.UUID, data: ModelIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    m = db.get(AIModel, model_id)
    if m is None:
        raise NotFound()
    values = data.model_dump(exclude_unset=True)
    old = {k: getattr(m, k) for k in values}
    for k, v in values.items():
        setattr(m, k, v)
    if values.get("is_default"):
        _single_default(db, m)
    audit.record(
        db, actor, tenant_id=None, entity="ai_model", entity_id=m.id, action="update", old=old, new=values
    )
    return model_dict(m, db.get(AIProvider, m.provider_id))


@router.delete("/api/admin/ai/models/{model_id}")
def delete_model(model_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    m = db.get(AIModel, model_id)
    if m is None:
        raise NotFound()
    m.active = False
    audit.record(db, actor, tenant_id=None, entity="ai_model", entity_id=m.id, action="deactivate")
    return {"ok": True}


# ------------------------------------------------------------------------------ prompts


class PromptIn(BaseModel):
    function: str
    system: str
    instructions: str = ""
    note: str | None = None


def prompt_dict(p: PromptTemplate) -> dict[str, Any]:
    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "function": p.function,
        "version": p.version,
        "system": p.system,
        "instructions": p.instructions,
        "active": p.active,
        "note": p.note,
        "created_at": p.created_at,
    }


@router.get("/api/ai/prompts")
def list_prompts(actor: CurrentActor, db: DB, function: str | None = None) -> dict[str, Any]:
    """Prompt versions: global (admin) and, for tenants, their own overrides."""
    if actor.tenant_id is None:
        actor.require("platform.ai")
    else:
        actor.require("tenant.settings")
    stmt = select(PromptTemplate)
    if actor.tenant_id is None:
        stmt = stmt.where(PromptTemplate.tenant_id.is_(None))
    if function:
        stmt = stmt.where(PromptTemplate.function == function)
    rows = list(db.scalars(stmt.order_by(PromptTemplate.function, PromptTemplate.version.desc())))
    effective = {f: prompt_for(db, actor.tenant_id, f).get("version") for f in FUNCTIONS}
    return {
        "functions": list(FUNCTIONS),
        "prompts": [prompt_dict(p) for p in rows],
        "effective_version": effective,
    }


@router.post("/api/ai/prompts", status_code=201)
def new_prompt_version(data: PromptIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Creates a new active version (admin: global; tenant: override for the tenant)."""
    if actor.tenant_id is None:
        actor.require("platform.ai")
    else:
        actor.require("tenant.settings")
    if data.function not in FUNCTIONS:
        raise AppError("errors.validation")
    tid = actor.tenant_id
    cond = PromptTemplate.tenant_id.is_(None) if tid is None else PromptTemplate.tenant_id == tid
    latest = (
        db.scalar(
            select(func.max(PromptTemplate.version)).where(cond, PromptTemplate.function == data.function)
        )
        or 0
    )
    for old in db.scalars(select(PromptTemplate).where(cond, PromptTemplate.function == data.function)):
        old.active = False
    p = PromptTemplate(
        tenant_id=tid,
        function=data.function,
        version=latest + 1,
        system=data.system,
        instructions=data.instructions,
        note=data.note,
        active=True,
        created_by=actor.user_id,
    )
    db.add(p)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="prompt",
        entity_id=p.id,
        action="create",
        new={"function": p.function, "version": p.version},
    )
    return prompt_dict(p)


@router.post("/api/ai/prompts/{prompt_id}/activate")
def activate_prompt(prompt_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    p = db.get(PromptTemplate, prompt_id)
    if p is None or p.tenant_id != actor.tenant_id:
        raise NotFound()
    actor.require("platform.ai" if actor.tenant_id is None else "tenant.settings")
    cond = (
        PromptTemplate.tenant_id.is_(None) if p.tenant_id is None else PromptTemplate.tenant_id == p.tenant_id
    )
    for other in db.scalars(select(PromptTemplate).where(cond, PromptTemplate.function == p.function)):
        other.active = other.id == p.id
    audit.record(db, actor, tenant_id=p.tenant_id, entity="prompt", entity_id=p.id, action="activate")
    return prompt_dict(p)


@router.delete("/api/ai/prompts/{prompt_id}")
def deactivate_prompt(prompt_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Deactivating a tenant override returns the tenant to the global prompt."""
    p = db.get(PromptTemplate, prompt_id)
    if p is None or p.tenant_id != actor.tenant_id:
        raise NotFound()
    actor.require("platform.ai" if actor.tenant_id is None else "tenant.settings")
    p.active = False
    return prompt_dict(p)


# ------------------------------------------------------------------------------ tenant: models, usage, keys


@router.get("/api/ai/models")
def available_models(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    providers = {p.id: p for p in db.scalars(select(AIProvider).where(AIProvider.active.is_(True)))}
    return [
        model_dict(m, providers[m.provider_id])
        for m in db.scalars(select(AIModel).where(AIModel.active.is_(True)).order_by(AIModel.label))
        if m.provider_id in providers
    ]


def usage_summary(db, tenant_id: uuid.UUID | None, since: datetime) -> list[dict[str, Any]]:
    stmt = (
        select(
            AIUsage.tenant_id,
            AIUsage.function,
            AIUsage.model,
            AIUsage.key_mode,
            func.count(),
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
            func.sum(AIUsage.cost_eur),
            func.count().filter(AIUsage.success.is_(False)),
        )
        .where(AIUsage.created_at >= since)
        .group_by(AIUsage.tenant_id, AIUsage.function, AIUsage.model, AIUsage.key_mode)
    )
    if tenant_id is not None:
        stmt = stmt.where(AIUsage.tenant_id == tenant_id)
    out = []
    for tid, fn, model, mode, n, tin, tout, cost, failed in db.execute(stmt).all():
        out.append(
            {
                "tenant_id": tid,
                "function": fn,
                "model": model,
                "key_mode": mode,
                "calls": n,
                "failed": failed,
                "input_tokens": int(tin or 0),
                "output_tokens": int(tout or 0),
                "cost_eur": round(float(cost or 0), 4),
            }
        )
    return out


@router.get("/api/ai/usage")
def my_usage(actor: CurrentActor, db: DB, months: int = 1) -> dict[str, Any]:
    now = datetime.now(UTC)
    year, month = now.year, now.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    since = datetime(year, month, 1, tzinfo=UTC)
    if actor.tenant_id is None:
        actor.require("platform.ai")
        names = {t.id: t.name for t in db.scalars(select(Tenant))}
        rows = usage_summary(db, None, since)
        for r in rows:
            r["tenant_name"] = names.get(r["tenant_id"], "Plattform")
        return {"since": since, "rows": rows}
    if not actor.has("ai.use"):
        actor.require("tenant.billing")
    resolver = SettingsResolver(db, actor.tenant_id)
    return {
        "since": since,
        "rows": usage_summary(db, actor.tenant_id, since),
        "status": spend_status(db, actor.tenant_id, resolver),
    }


class KeyIn(BaseModel):
    provider_id: uuid.UUID
    api_key: str


@router.get("/api/ai/keys")
def list_keys(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("tenant.settings")
    tid = actor.require_tenant()
    return [
        {"id": k.id, "provider_id": k.provider_id, "key_hint": k.key_hint, "updated_at": k.updated_at}
        for k in db.scalars(select(TenantAIKey).where(TenantAIKey.tenant_id == tid))
    ]


@router.put("/api/ai/keys")
def put_key(data: KeyIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Store the tenant's own API key (encrypted). The key is never returned, only its last characters."""
    actor.require("tenant.settings")
    tid = actor.require_tenant()
    if db.get(AIProvider, data.provider_id) is None:
        raise NotFound()
    row = db.scalar(
        select(TenantAIKey).where(TenantAIKey.tenant_id == tid, TenantAIKey.provider_id == data.provider_id)
    )
    if row is None:
        row = TenantAIKey(tenant_id=tid, provider_id=data.provider_id, api_key_enc="", key_hint="")
        db.add(row)
    row.api_key_enc = encrypt(data.api_key.strip())
    row.key_hint = "…" + data.api_key.strip()[-4:]
    audit.record(
        db,
        actor,
        tenant_id=tid,
        entity="ai_key",
        entity_id=data.provider_id,
        action="set",
        new={"hint": row.key_hint},
    )
    return {"ok": True, "key_hint": row.key_hint}


@router.delete("/api/ai/keys/{provider_id}")
def delete_key(provider_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.settings")
    tid = actor.require_tenant()
    row = db.scalar(
        select(TenantAIKey).where(TenantAIKey.tenant_id == tid, TenantAIKey.provider_id == provider_id)
    )
    if row is not None:
        db.delete(row)
        audit.record(db, actor, tenant_id=tid, entity="ai_key", entity_id=provider_id, action="delete")
    return {"ok": True}


# ------------------------------------------------------------------------------ order photo checks


@router.post("/api/orders/{order_id}/photo-check")
def order_photo_check(order_id: uuid.UUID, actor: CurrentActor, db: DB, sync: bool = False) -> dict[str, Any]:
    actor.require("orders.write", "ai.use")
    order = db.get(PickupOrder, order_id)
    if order is None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    job = enqueue(
        db,
        "ai.check_order_photos",
        {"order_id": str(order.id)},
        tenant_id=order.tenant_id,
        created_by=actor.user_id,
    )
    if sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result}


@router.post("/api/orders/{order_id}/photo-analysis")
def order_photo_analysis(
    order_id: uuid.UUID, actor: CurrentActor, db: DB, sync: bool = False
) -> dict[str, Any]:
    actor.require("orders.write", "ai.use")
    order = db.get(PickupOrder, order_id)
    if order is None or order.tenant_id != actor.tenant_id:
        raise NotFound()
    job = enqueue(
        db,
        "ai.analyse_order_photos",
        {"order_id": str(order.id)},
        tenant_id=order.tenant_id,
        created_by=actor.user_id,
    )
    if sync:
        job = run_now(db, job)
    return {"job_id": job.id, "status": job.status, "result": job.result}


# ------------------------------------------------------------------------------ evaluation tool (admin)


@router.get("/api/admin/ai/eval-sets")
def eval_sets(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("platform.ai")
    out = []
    for s in db.scalars(
        select(EvalSet).where(EvalSet.tenant_id.is_(None)).order_by(EvalSet.created_at.desc())
    ):
        items = list(db.scalars(select(EvalItem).where(EvalItem.set_id == s.id)))
        runs = list(
            db.scalars(select(EvalRun).where(EvalRun.set_id == s.id).order_by(EvalRun.created_at.desc()))
        )
        models = {m.id: m.label for m in db.scalars(select(AIModel))}
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "notes": s.notes,
                "items": [
                    {"id": i.id, "label": i.label, "truth": i.truth, "photos": i.photo_file_ids}
                    for i in items
                ],
                "runs": [
                    {
                        "id": r.id,
                        "model": models.get(r.model_id),
                        "model_id": r.model_id,
                        "status": r.status,
                        "metrics": r.metrics,
                        "created_at": r.created_at,
                    }
                    for r in runs
                ],
            }
        )
    return out


class EvalSetIn(BaseModel):
    name: str
    notes: str | None = None


@router.post("/api/admin/ai/eval-sets", status_code=201)
def create_eval_set(data: EvalSetIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("platform.ai")
    s = EvalSet(tenant_id=None, name=data.name, notes=data.notes)
    db.add(s)
    db.flush()
    return {"id": s.id, "name": s.name}


@router.post("/api/admin/ai/eval-sets/{set_id}/items", status_code=201)
async def add_eval_item(
    set_id: uuid.UUID,
    actor: CurrentActor,
    db: DB,
    label: str = Form(...),
    truth: str = Form("{}", description='JSON, z. B. {"total_height_cm": 180, "pot_diameter_cm": 50}'),
    kinds: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    import json

    actor.require("platform.ai")
    if db.get(EvalSet, set_id) is None:
        raise NotFound()
    file_ids = []
    for i, f in enumerate(files):
        clean, w, h = clean_image(await f.read())
        stored = store_file(db, actor, clean, f.filename or "eval.jpg", "image/jpeg", "eval")
        file_ids.append(
            {
                "file_id": str(stored.id),
                "kind": kinds[i] if i < len(kinds) else "plant_front",
                "width": w,
                "height": h,
            }
        )
    item = EvalItem(
        tenant_id=None, set_id=set_id, label=label, truth=json.loads(truth or "{}"), photo_file_ids=file_ids
    )
    db.add(item)
    db.flush()
    return {"id": item.id}


class EvalRunIn(BaseModel):
    model_ids: list[uuid.UUID]
    sync: bool = False


@router.post("/api/admin/ai/eval-sets/{set_id}/run")
def run_eval(set_id: uuid.UUID, data: EvalRunIn, actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    """Compare several models on a test set (mean error per quantity, cost per evaluation)."""
    actor.require("platform.ai")
    out = []
    for mid in data.model_ids:
        run = EvalRun(tenant_id=None, set_id=set_id, model_id=mid, status="queued")
        db.add(run)
        db.flush()
        job = enqueue(db, "ai.eval_run", {"run_id": str(run.id)}, tenant_id=None, created_by=actor.user_id)
        run.job_id = job.id
        if data.sync:
            run_now(db, job)
            db.refresh(run)
        out.append({"id": run.id, "status": run.status, "metrics": run.metrics})
    return out
